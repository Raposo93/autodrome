#!/usr/bin/env python3
"""Opt-in full-pipeline benchmark for experimental track concurrency."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from yt_dlp.version import __version__ as yt_dlp_version

from autodrome import config
from autodrome.controllers.downloader_controller import DownloaderController
from autodrome.models.track import Track
from autodrome.services import organizer as organizer_module
from autodrome.services.organizer import Organizer
from autodrome.yt_downloader import YTDownloader


DEFAULT_LEVELS = (1, 2, 4, 8, 12, 20)
EXPERIMENTAL_MAX_CONCURRENCY = 20
THROTTLING_MARKERS = ("429", "too many requests", "throttl")


class BenchmarkDownloader(YTDownloader):
    """Instrument the real downloader without widening production settings."""

    def __init__(self, concurrency: int, track_download_attempts: int = 2) -> None:
        if not 1 <= concurrency <= EXPERIMENTAL_MAX_CONCURRENCY:
            raise ValueError(
                "benchmark concurrency must be between 1 and "
                f"{EXPERIMENTAL_MAX_CONCURRENCY}"
            )
        super().__init__(
            track_download_attempts=track_download_attempts,
            download_concurrency=1,
        )
        # Production construction still rejects values above MAX_DOWNLOAD_CONCURRENCY.
        # This local subclass is the explicit, opt-in experimental boundary.
        self.download_concurrency = concurrency
        self._measurement_lock = threading.Lock()
        self.active_downloads = 0
        self.peak_active_downloads = 0
        self.attempts_by_track: Counter[int] = Counter()
        self.attempt_errors: list[dict[str, Any]] = []
        self.provider_messages: list[dict[str, Any]] = []

    def _build_ydl_opts(self, dest: Path, hook, index: int) -> dict:
        options = super()._build_ydl_opts(dest, hook, index)
        options["logger"] = BenchmarkYdlLogger(self)
        return options

    def record_provider_message(self, level: str, message: str) -> None:
        throttling = is_throttling_error(message)
        if level in {"warning", "error"} or throttling:
            with self._measurement_lock:
                self.provider_messages.append({
                    "level": level,
                    "message": message,
                    "throttling": throttling,
                })

    def _download_track_blocking(self, url: str, dest: str, index: int, hook) -> None:
        with self._measurement_lock:
            self.active_downloads += 1
            self.peak_active_downloads = max(
                self.peak_active_downloads,
                self.active_downloads,
            )
            self.attempts_by_track[index] += 1
        try:
            super()._download_track_blocking(url, dest, index, hook)
        except Exception as error:
            with self._measurement_lock:
                self.attempt_errors.append({
                    "track": index,
                    "error": str(error),
                    "throttling": is_throttling_error(error),
                })
            raise
        finally:
            with self._measurement_lock:
                self.active_downloads -= 1


class BenchmarkYdlLogger:
    def __init__(self, downloader: BenchmarkDownloader) -> None:
        self.downloader = downloader

    def debug(self, message: str) -> None:
        self.downloader.record_provider_message("debug", message)

    def info(self, message: str) -> None:
        self.downloader.record_provider_message("info", message)

    def warning(self, message: str) -> None:
        self.downloader.record_provider_message("warning", message)

    def error(self, message: str) -> None:
        self.downloader.record_provider_message("error", message)


class ProcessTreeSampler:
    def __init__(self, root_pid: int, disk_path: Path, interval: float) -> None:
        self.root_pid = root_pid
        self.disk_path = disk_path
        self.interval = interval
        self.peak_rss_bytes = 0
        self.peak_cpu_percent = 0.0
        self.peak_ffmpeg_processes = 0
        self.minimum_free_bytes = shutil.disk_usage(disk_path).free
        self._previous_cpu: dict[int, float] | None = None
        self._previous_time: float | None = None

    async def run(self, stopped: asyncio.Event) -> None:
        self.sample()
        while not stopped.is_set():
            try:
                await asyncio.wait_for(stopped.wait(), timeout=self.interval)
            except TimeoutError:
                self.sample()
        self.sample()

    def sample(self) -> None:
        now = time.monotonic()
        processes = read_process_tree(self.root_pid)
        self.peak_rss_bytes = max(
            self.peak_rss_bytes,
            sum(process["rss_bytes"] for process in processes.values()),
        )
        self.peak_ffmpeg_processes = max(
            self.peak_ffmpeg_processes,
            sum("ffmpeg" in process["name"].lower() for process in processes.values()),
        )
        current_cpu = {
            pid: process["cpu_seconds"] for pid, process in processes.items()
        }
        if self._previous_cpu is not None and self._previous_time is not None:
            elapsed = now - self._previous_time
            if elapsed > 0:
                cpu_delta = sum(
                    max(0.0, cpu - self._previous_cpu.get(pid, cpu))
                    for pid, cpu in current_cpu.items()
                )
                self.peak_cpu_percent = max(
                    self.peak_cpu_percent,
                    100.0 * cpu_delta / elapsed,
                )
        self._previous_cpu = current_cpu
        self._previous_time = now
        self.minimum_free_bytes = min(
            self.minimum_free_bytes,
            shutil.disk_usage(self.disk_path).free,
        )


def is_throttling_error(error: BaseException | str) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in THROTTLING_MARKERS)


def read_process_tree(root_pid: int) -> dict[int, dict[str, Any]]:
    """Return approximate Linux /proc metrics for a process and descendants."""
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return {}
    ticks = os.sysconf("SC_CLK_TCK")
    page_size = os.sysconf("SC_PAGE_SIZE")
    all_processes: dict[int, dict[str, Any]] = {}
    children: dict[int, list[int]] = {}
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text()
            name_end = raw.rfind(")")
            name = raw[raw.find("(") + 1:name_end]
            fields = raw[name_end + 2:].split()
            pid = int(entry.name)
            parent = int(fields[1])
            all_processes[pid] = {
                "parent": parent,
                "name": name,
                "cpu_seconds": (int(fields[11]) + int(fields[12])) / ticks,
                "rss_bytes": max(0, int(fields[21])) * page_size,
            }
            children.setdefault(parent, []).append(pid)
        except (FileNotFoundError, PermissionError, ProcessLookupError, ValueError, IndexError):
            continue

    selected: dict[int, dict[str, Any]] = {}
    pending = [root_pid]
    while pending:
        pid = pending.pop()
        process = all_processes.get(pid)
        if process is None or pid in selected:
            continue
        selected[pid] = process
        pending.extend(children.get(pid, []))
    return selected


def validate_levels(levels: Iterable[int]) -> list[int]:
    values = list(levels)
    if not values:
        raise ValueError("at least one concurrency level is required")
    if any(level < 1 or level > EXPERIMENTAL_MAX_CONCURRENCY for level in values):
        raise ValueError(
            f"levels must be between 1 and {EXPERIMENTAL_MAX_CONCURRENCY}"
        )
    if values != sorted(set(values)):
        raise ValueError("levels must be unique and strictly increasing")
    return values


def prepare_output_root(raw_path: str | None) -> Path:
    temporary_root = Path(tempfile.gettempdir()).resolve()
    if raw_path is None:
        return Path(tempfile.mkdtemp(prefix="autodrome-concurrency-benchmark-"))

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        raise ValueError("--output-root must be an absolute path")
    resolved = candidate.resolve(strict=False)
    if resolved == temporary_root or temporary_root not in resolved.parents:
        raise ValueError(
            f"--output-root must be a new directory below {temporary_root}"
        )
    if candidate.exists() or candidate.is_symlink():
        raise ValueError("--output-root must not already exist")
    candidate.mkdir()
    return resolved


def command_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = result.stdout or result.stderr
    return output.splitlines()[0] if output else None


def cpu_model() -> str | None:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return platform.processor() or None


def total_memory_bytes() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def git_revision() -> str | None:
    return command_version(["git", "rev-parse", "--short", "HEAD"])


def file_inventory(folder: Path) -> list[dict[str, Any]]:
    inventory = []
    for path in sorted(folder.glob("*.mp3")):
        digest = hashlib.sha256()
        with path.open("rb") as file_handle:
            for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
                digest.update(chunk)
        inventory.append({
            "name": path.name,
            "bytes": path.stat().st_size,
            "sha256": digest.hexdigest(),
        })
    return inventory


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [run for run in runs if run["status"] == "passed"]
    failed = [run for run in runs if run["status"] != "passed"]
    highest_successful = max(
        (run["concurrency"] for run in successful),
        default=None,
    )
    supported = [
        run for run in successful
        if run["concurrency"] <= config.MAX_DOWNLOAD_CONCURRENCY
    ]
    recommended = None
    if supported:
        best_throughput = max(run["throughput_tracks_per_second"] for run in supported)
        near_best = [
            run for run in supported
            if run["throughput_tracks_per_second"] >= best_throughput * 0.9
        ]
        recommended = min(run["concurrency"] for run in near_best)
    return {
        "highest_successful_experimental_level": highest_successful,
        "first_failed_level": failed[0]["concurrency"] if failed else None,
        "recommended_supported_level_on_this_host": recommended,
        "production_default_unchanged": 1,
        "production_maximum_unchanged": config.MAX_DOWNLOAD_CONCURRENCY,
        "break_point_observed": bool(failed),
    }


def render_markdown(report: dict[str, Any]) -> str:
    environment = report["environment"]
    lines = [
        "# Autodrome download concurrency benchmark",
        "",
        f"Started: {report['started_at']}",
        f"Host: {environment['hostname']} · {environment['platform']}",
        f"CPU: {environment['cpu_model']} ({environment['cpu_count']} logical CPUs)",
        f"Memory: {environment['total_memory_bytes']} bytes",
        f"ffmpeg: {environment['ffmpeg']}",
        f"yt-dlp: {environment['yt_dlp']}",
        f"Git: {environment['git_revision']}",
        "",
        "| concurrency | result | seconds | tracks/s | peak active | peak ffmpeg | peak CPU % | peak RSS MiB | retries | 429/throttle | integrity |",
        "| ---: | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |",
    ]
    for run in report["runs"]:
        lines.append(
            "| {concurrency} | {status} | {elapsed_seconds:.2f} | "
            "{throughput_tracks_per_second:.3f} | {peak_active_downloads} | "
            "{peak_ffmpeg_processes} | {peak_process_tree_cpu_percent:.1f} | "
            "{peak_process_tree_rss_mib:.1f} | {retry_attempts} | "
            "{throttling_errors} | {integrity_label} |".format(
                integrity_label="yes" if run["integrity"]["valid"] else "no",
                **run,
            )
        )
    summary = report["summary"]
    lines.extend([
        "",
        "## Interpretation",
        "",
        f"Highest successful experimental level: {summary['highest_successful_experimental_level']}.",
        f"First failed level: {summary['first_failed_level']}.",
        "Conservative supported recommendation for this host: "
        f"{summary['recommended_supported_level_on_this_host']}.",
        "The production default remains 1 and the supported maximum remains "
        f"{summary['production_maximum_unchanged']}; experimental success above it does not widen support.",
        "",
    ])
    return "\n".join(lines)


def write_report(report: dict[str, Any], output_root: Path) -> None:
    report["summary"] = summarize_runs(report["runs"])
    (output_root / "results.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "results.md").write_text(
        render_markdown(report),
        encoding="utf-8",
    )


async def run_level(
    *,
    level: int,
    level_root: Path,
    manifest: dict[str, Any],
    playlist_url: str,
    expected_tracks: int,
    artist: str,
    album: str,
    attempts: int,
    sample_interval: float,
) -> dict[str, Any]:
    library_root = level_root / "library"
    staging_root = level_root / "staging"
    level_root.mkdir()
    organizer_module.conf.library_path = str(library_root)
    organizer_module.conf.staging_path = str(staging_root)
    organizer_module.conf.preserve_failed_staging = True

    downloader = BenchmarkDownloader(level, track_download_attempts=attempts)
    downloader._manifests[playlist_url] = (time.monotonic(), manifest)
    organizer = Organizer()
    controller = DownloaderController(
        downloader=downloader,
        organizer=organizer,
        metadata_service=object(),
    )
    progress_events = []
    started = time.monotonic()

    async def progress(phase, current, total, completed) -> None:
        progress_events.append({
            "seconds": round(time.monotonic() - started, 3),
            "phase": phase,
            "current": current,
            "total": total,
            "completed": completed,
        })

    disk_before = shutil.disk_usage(level_root).free
    stopped = asyncio.Event()
    sampler = ProcessTreeSampler(os.getpid(), level_root, sample_interval)
    sampler_task = asyncio.create_task(sampler.run(stopped))
    error_message = None
    published_folder = None
    inventory: list[dict[str, Any]] = []
    try:
        await controller.download_and_tag(
            playlist_url=playlist_url,
            artist=artist,
            album=album,
            release_id=None,
            track_count=expected_tracks,
            metadata_mode="manual",
            manual_confirmed=True,
            progress=progress,
        )
        published_folder = Path(organizer._get_album_folder(artist, album))
        tracks = [
            Track(number=entry["position"], title=entry["title"])
            for entry in manifest["tracks"]
        ]
        organizer.validate_album(str(published_folder), artist, album, tracks)
        inventory = file_inventory(published_folder)
    except Exception as error:
        error_message = f"{type(error).__name__}: {error}"
    finally:
        stopped.set()
        await sampler_task

    elapsed = time.monotonic() - started
    disk_after = shutil.disk_usage(level_root).free
    attempts_total = sum(downloader.attempts_by_track.values())
    retry_attempts = max(0, attempts_total - len(downloader.attempts_by_track))
    passed = error_message is None
    return {
        "concurrency": level,
        "status": "passed" if passed else "failed",
        "error": error_message,
        "elapsed_seconds": round(elapsed, 3),
        "throughput_tracks_per_second": round(expected_tracks / elapsed, 6) if passed else 0.0,
        "peak_active_downloads": downloader.peak_active_downloads,
        "peak_ffmpeg_processes": sampler.peak_ffmpeg_processes,
        "peak_process_tree_cpu_percent": round(sampler.peak_cpu_percent, 3),
        "peak_process_tree_rss_mib": round(sampler.peak_rss_bytes / (1024 * 1024), 3),
        "minimum_free_bytes": sampler.minimum_free_bytes,
        "free_bytes_delta": disk_after - disk_before,
        "published_bytes": sum(file["bytes"] for file in inventory),
        "attempts": attempts_total,
        "retry_attempts": retry_attempts,
        "attempts_by_track": dict(sorted(downloader.attempts_by_track.items())),
        "retry_attempts_by_track": {
            track: max(0, attempts - 1)
            for track, attempts in sorted(downloader.attempts_by_track.items())
        },
        "attempt_errors": downloader.attempt_errors,
        "provider_messages": downloader.provider_messages,
        "throttling_errors": sum(
            error["throttling"] for error in downloader.attempt_errors
        ) + sum(message["throttling"] for message in downloader.provider_messages),
        "progress_events": progress_events,
        "integrity": {
            "valid": passed and len(inventory) == expected_tracks,
            "published_folder": str(published_folder) if published_folder else None,
            "file_count": len(inventory),
            "files": inventory,
        },
    }


async def run_benchmark(args: argparse.Namespace) -> Path:
    levels = validate_levels(args.levels)
    output_root = prepare_output_root(args.output_root)
    environment = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_model": cpu_model(),
        "cpu_count": os.cpu_count(),
        "total_memory_bytes": total_memory_bytes(),
        "ffmpeg": command_version(["ffmpeg", "-version"]),
        "yt_dlp": yt_dlp_version,
        "git_revision": git_revision(),
        "filesystem_device": output_root.stat().st_dev,
        "initial_free_bytes": shutil.disk_usage(output_root).free,
    }
    report = {
        "schema_version": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "environment": environment,
        "configuration": {
            "playlist_url": args.playlist_url,
            "expected_tracks": args.expected_tracks,
            "artist": args.artist,
            "album": args.album,
            "levels": levels,
            "track_download_attempts": args.attempts,
            "sample_interval_seconds": args.sample_interval,
            "output_root": str(output_root),
            "production_default": 1,
            "production_maximum": config.MAX_DOWNLOAD_CONCURRENCY,
        },
        "manifest": None,
        "runs": [],
        "summary": {},
    }
    try:
        manifest_downloader = YTDownloader(track_download_attempts=args.attempts)
        manifest = await manifest_downloader.get_playlist_manifest(
            args.playlist_url,
            args.expected_tracks,
        )
        report["manifest"] = {
            "track_count": manifest["track_count"],
            "unavailable": manifest["unavailable"],
            "tracks": manifest["tracks"],
        }
        for level in levels:
            result = await run_level(
                level=level,
                level_root=output_root / f"concurrency-{level}",
                manifest=manifest,
                playlist_url=args.playlist_url,
                expected_tracks=args.expected_tracks,
                artist=args.artist,
                album=args.album,
                attempts=args.attempts,
                sample_interval=args.sample_interval,
            )
            report["runs"].append(result)
            write_report(report, output_root)
            if result["status"] != "passed":
                break
    finally:
        write_report(report, output_root)
    return output_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playlist-url", required=True)
    parser.add_argument("--expected-tracks", type=int, required=True)
    parser.add_argument("--artist", required=True)
    parser.add_argument("--album", required=True)
    parser.add_argument("--levels", type=int, nargs="+", default=list(DEFAULT_LEVELS))
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--sample-interval", type=float, default=0.2)
    parser.add_argument("--output-root")
    parser.add_argument(
        "--confirm-disposable",
        action="store_true",
        help="confirm that this is a disposable host and scratch run",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def validate_arguments(args: argparse.Namespace) -> None:
    validate_levels(args.levels)
    parsed_url = urlsplit(args.playlist_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("--playlist-url must be an HTTP(S) URL")
    if parsed_url.username or parsed_url.password:
        raise ValueError("--playlist-url must not contain credentials")
    if args.expected_tracks < 1:
        raise ValueError("--expected-tracks must be positive")
    if args.attempts < 1:
        raise ValueError("--attempts must be positive")
    if args.sample_interval <= 0:
        raise ValueError("--sample-interval must be positive")
    if not args.dry_run and not args.confirm_disposable:
        raise ValueError("--confirm-disposable is required for a real benchmark")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        validate_arguments(args)
    except ValueError as error:
        parser.error(str(error))
    if args.dry_run:
        print(json.dumps({
            "playlist_url": args.playlist_url,
            "expected_tracks": args.expected_tracks,
            "levels": validate_levels(args.levels),
            "production_maximum_unchanged": config.MAX_DOWNLOAD_CONCURRENCY,
        }, indent=2))
        return 0
    try:
        output_root = asyncio.run(run_benchmark(args))
    except KeyboardInterrupt:
        print("Benchmark interrupted; inspect the output directory before removing it.")
        return 130
    except Exception as error:
        print(f"Benchmark setup failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(f"Benchmark complete: {output_root / 'results.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
