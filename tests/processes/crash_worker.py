"""Run a disposable Autodrome worker for the SIGKILL integration test."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from autodrome.controllers.downloader_controller import DownloaderController
from autodrome.models.release import Release
from autodrome.models.track import Track
from autodrome.services import organizer as organizer_module
from autodrome.services.download_queue import DownloadQueueManager
from autodrome.services.organizer import Organizer


def payload(album: str) -> dict:
    return {
        "playlist_url": f"fixture://{album}",
        "artist": "Artist",
        "album": album,
        "release_id": f"release-{album}",
        "track_count": 1,
    }


class LocalMetadata:
    async def get_release(self, release_id: str) -> Release:
        album = release_id.removeprefix("release-")
        return Release(
            release_id=release_id,
            title=album,
            date="2026",
            artist="Artist",
            cover_url=None,
            tracks=[Track(1, "Track")],
        )

    async def get_cover_art(self, release_id: str):
        return None


class LocalAudioDownloader:
    def __init__(self, scenario: str, ready_fd: int) -> None:
        self.scenario = scenario
        self.ready_fd = ready_fd

    async def download_playlist(self, url, destination, total, progress, **kwargs):
        await progress("manifest", None, None, None)
        await progress("downloading", 1, total, 0)
        destination_path = Path(destination)
        if self.scenario == "during_download":
            (destination_path / "01 - Source.part").write_bytes(b"partial audio")
            os.write(self.ready_fd, b"during_download\n")
            await asyncio.Event().wait()
        (destination_path / "01 - Source.mp3").write_bytes(b"ID3")
        await progress("downloading", 1, total, 1)


class RecordingController:
    def __init__(self, calls_path: Path) -> None:
        self.calls_path = calls_path

    async def download_and_tag(self, album, **kwargs):
        calls = []
        if self.calls_path.exists():
            calls = json.loads(self.calls_path.read_text(encoding="utf-8"))
        calls.append(album)
        self.calls_path.write_text(json.dumps(calls), encoding="utf-8")


def configure_paths(root: Path) -> None:
    organizer_module.conf.library_path = str(root / "library")
    organizer_module.conf.staging_path = str(root / "staging")
    organizer_module.conf.minimum_staging_free_bytes = 0
    organizer_module.conf.preserve_failed_staging = True


async def run_crash_scenario(
    scenario: str,
    root: Path,
    ready_fd: int,
    hold_fd: int,
) -> None:
    configure_paths(root)
    organizer = Organizer()
    # Audio bytes are deliberately synthetic; exercise filesystem lifecycle,
    # while real Mutagen behavior remains covered by the normal test suite.
    organizer.tagger.tag_files = lambda *args, **kwargs: None
    organizer.validate_album = lambda *args, **kwargs: None
    controller = DownloaderController(
        LocalAudioDownloader(scenario, ready_fd),
        organizer,
        LocalMetadata(),
    )
    manager = DownloadQueueManager(
        controller,
        websocket_manager=NoopWebSocketManager(),
        state_path=str(root / "queue.json"),
    )
    first_job = await manager.enqueue(payload("Album"))
    await manager.enqueue(payload("Queued Album"))

    if scenario == "after_publish":
        persist_state = manager._persist_state

        def stop_before_succeeded_write():
            if manager._jobs[first_job].status == "succeeded":
                os.write(ready_fd, b"after_publish\n")
                os.read(hold_fd, 1)
            persist_state()

        manager._persist_state = stop_before_succeeded_write

    manager.start()
    await manager.queue.join()
    raise AssertionError(f"Crash scenario '{scenario}' unexpectedly completed")


async def run_recovery(root: Path) -> None:
    calls_path = root / "recovery-calls.json"
    manager = DownloadQueueManager(
        RecordingController(calls_path),
        websocket_manager=NoopWebSocketManager(),
        state_path=str(root / "queue.json"),
    )
    try:
        manager.start()
        await manager.queue.join()
        (root / "recovery-snapshot.json").write_text(
            json.dumps(manager.snapshot(), indent=2),
            encoding="utf-8",
        )
    finally:
        await manager.stop()


class NoopWebSocketManager:
    async def broadcast(self, message) -> None:
        return None


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=("during_download", "after_publish", "recover"),
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--ready-fd", type=int)
    parser.add_argument("--hold-fd", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    if args.mode == "recover":
        asyncio.run(run_recovery(args.root))
        return
    if args.ready_fd is None or args.hold_fd is None:
        raise SystemExit("Crash modes require --ready-fd and --hold-fd")
    asyncio.run(
        run_crash_scenario(
            args.mode,
            args.root,
            args.ready_fd,
            args.hold_fd,
        )
    )


if __name__ == "__main__":
    main()
