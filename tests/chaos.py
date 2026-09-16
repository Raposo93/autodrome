"""Seeded, disposable chaos campaign for Autodrome's durable album workflow.

This module deliberately lives under ``tests``.  It uses simulated providers,
synthetic audio files and temporary library roots; production code must never
import it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
from collections import Counter, defaultdict
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

from autodrome.http_client_async import UpstreamServiceError
from autodrome.models.download_job import RETRYABLE_STATUSES, TERMINAL_STATUSES
from autodrome.services import organizer as organizer_module
from autodrome.services.download_queue import DownloadQueueManager
from autodrome.services.organizer import Organizer
from tests.fault_injection import FaultInjector, NoSpaceError


CHAOS_VERSION = 1
SCENARIO = "album-download"
FAULT_KINDS = (
    "success",
    "provider_failure",
    "track_failure",
    "filesystem_failure",
    "queue_write_failure",
    "running_cancel",
    "restart",
)


@dataclass(frozen=True)
class ChaosPlan:
    order: int
    kind: str
    album: str
    track_count: int
    failure_track: int | None
    provider_status: int | None
    latency_ticks: int

    @property
    def payload(self) -> dict[str, Any]:
        slug = self.album.lower().replace(" ", "-")
        return {
            "playlist_url": f"fixture://{slug}",
            "artist": "Chaos Artist",
            "album": self.album,
            "release_id": f"release-{slug}",
            "track_count": self.track_count,
        }


class ChaosFailure(AssertionError):
    """Failure with everything needed to replay a campaign exactly."""

    def __init__(
        self,
        *,
        seed: int,
        reason: str,
        events: list[dict[str, Any]],
        last_state: list[dict[str, Any]],
    ) -> None:
        self.seed = seed
        self.reason = reason
        self.events = events
        self.last_state = last_state
        self.reproduce = (
            "python scripts/chaos_test.py "
            f"--scenario {SCENARIO} --seed {seed}"
        )
        super().__init__(
            json.dumps(
                {
                    "result": "FAIL",
                    "scenario": SCENARIO,
                    "seed": seed,
                    "reason": reason,
                    "events": events,
                    "last_state": last_state,
                    "reproduce": self.reproduce,
                },
                indent=2,
                sort_keys=True,
            )
        )


class EventLog:
    def __init__(self, max_events: int) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        self.max_events = max_events
        self.events: list[dict[str, Any]] = []

    def add(self, event: str, **details: Any) -> None:
        if len(self.events) >= self.max_events:
            raise RuntimeError(
                f"Chaos event limit reached ({self.max_events}) before '{event}'"
            )
        self.events.append(
            {"number": len(self.events) + 1, "event": event, **details}
        )


class NoopWebSocketManager:
    async def broadcast(self, message: Any) -> None:
        return None


def build_plan(seed: int) -> tuple[list[ChaosPlan], int]:
    """Build the whole action plan before async execution starts."""
    rng = random.Random(seed)
    kinds = list(FAULT_KINDS)
    rng.shuffle(kinds)
    plans = []
    for order, kind in enumerate(kinds, start=1):
        track_count = rng.randint(1, 4)
        plans.append(
            ChaosPlan(
                order=order,
                kind=kind,
                album=f"Chaos {order:02d} {kind.replace('_', ' ').title()}",
                track_count=track_count,
                failure_track=(
                    rng.randint(1, track_count) if kind == "track_failure" else None
                ),
                provider_status=(
                    rng.choice((429, 504)) if kind == "provider_failure" else None
                ),
                latency_ticks=rng.randint(1, 3),
            )
        )
    return plans, rng.randint(1, 4)


class ChaosController:
    """Controlled provider and synthetic album pipeline using real queue/organizer."""

    def __init__(
        self,
        organizer: Organizer,
        plans: list[ChaosPlan],
        events: EventLog,
        download_concurrency: int,
    ) -> None:
        self.organizer = organizer
        self.plans = {plan.album: plan for plan in plans}
        self.events = events
        self.download_concurrency = download_concurrency
        self.attempts: defaultdict[str, int] = defaultdict(int)
        self.control_points: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self.faults: dict[str, FaultInjector] = {}
        for plan in plans:
            point = self._fault_point(plan)
            if point is not None:
                error_type = NoSpaceError if plan.kind == "filesystem_failure" else RuntimeError
                self.faults[plan.album] = FaultInjector(
                    f"seeded-{plan.kind}-{plan.order}",
                    {point: {1: error_type}},
                )

    async def ensure_destination_available(self, artist: str, album: str) -> None:
        destination = self.organizer.inspect_album_destination(artist, album)
        if destination["state"] == "exists":
            raise FileExistsError("Album already exists in the library")
        if destination["state"] != "not_found":
            raise OSError("Album destination could not be checked")

    async def download_and_tag(
        self,
        *,
        progress,
        job_id: str,
        artist: str,
        album: str,
        track_count: int,
        **kwargs: Any,
    ) -> None:
        plan = self.plans[album]
        self.attempts[album] += 1
        attempt = self.attempts[album]
        fault_active = attempt == 1
        self.events.add(
            "attempt_started",
            album=album,
            attempt=attempt,
            kind=plan.kind,
        )

        await progress("metadata", None, None, None)
        for tick in range(1, plan.latency_ticks + 1):
            self.events.add(
                "provider_latency",
                album=album,
                attempt=attempt,
                tick=tick,
            )
            await asyncio.sleep(0)

        if fault_active and plan.kind == "provider_failure":
            try:
                self.faults[album].hit("provider.musicbrainz.release")
            except RuntimeError as error:
                status = plan.provider_status
                reason = "rate limited" if status == 429 else "request timed out"
                self.events.add(
                    "fault_injected",
                    album=album,
                    point="provider.musicbrainz.release",
                    status=status,
                )
                raise UpstreamServiceError(
                    "MusicBrainz",
                    f"loading {kwargs.get('release_id', 'release')}",
                    reason,
                    attempts=3,
                    status=status,
                ) from error

        await progress("staging", None, None, None)
        with self.organizer.create_staging_folder(artist, album) as staging:
            staging_path = Path(staging)
            await progress("downloading", 1, track_count, 0)
            if fault_active and plan.kind in {"running_cancel", "restart"}:
                self.events.add(
                    "control_point",
                    album=album,
                    action=plan.kind,
                    phase="downloading",
                )
                await self.control_points.put((plan.kind, album))
                await asyncio.Event().wait()

            for track in range(1, track_count + 1):
                if (
                    fault_active
                    and plan.kind == "track_failure"
                    and track == plan.failure_track
                ):
                    point = f"download.track.{track}"
                    self.events.add(
                        "fault_injected",
                        album=album,
                        point=point,
                    )
                    self.faults[album].hit(point)
                (staging_path / f"{track:02d} - Track {track}.mp3").write_bytes(
                    f"synthetic audio {album} {track}\n".encode()
                )
                await progress("downloading", track, track_count, track)

            await progress("tagging", None, None, None)
            await progress("validating", None, None, None)
            files = sorted(staging_path.glob("*.mp3"))
            if len(files) != track_count or any(not path.read_bytes() for path in files):
                raise AssertionError("Synthetic staged album failed validation")
            (staging_path / ".autodrome-chaos-complete.json").write_text(
                json.dumps(
                    {
                        "album": album,
                        "track_count": track_count,
                        "validated": True,
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            await progress("publishing", None, None, None)
            if fault_active and plan.kind == "filesystem_failure":
                self.events.add(
                    "fault_injected",
                    album=album,
                    point="filesystem.publish.rename",
                )
                self.faults[album].hit("filesystem.publish.rename")
            self.organizer.move_to_library(staging, artist, album)
            self.events.add("album_published", album=album, attempt=attempt)

    @staticmethod
    def _fault_point(plan: ChaosPlan) -> str | None:
        if plan.kind == "provider_failure":
            return "provider.musicbrainz.release"
        if plan.kind == "track_failure":
            return f"download.track.{plan.failure_track}"
        if plan.kind == "filesystem_failure":
            return "filesystem.publish.rename"
        return None

    def assert_faults_reached(self) -> None:
        for faults in self.faults.values():
            faults.assert_complete()


class ChaosCampaign:
    def __init__(self, seed: int, max_events: int) -> None:
        self.seed = seed
        self.log = EventLog(max_events)
        self.plans, self.download_concurrency = build_plan(seed)
        self.manager: DownloadQueueManager | None = None
        self.queue_fault = FaultInjector(
            f"seeded-queue-write-{seed}",
            {"queue.persist.running": {1: NoSpaceError}},
        )
        self.queue_fault_injected = False

    async def run(self, root: Path) -> dict[str, Any]:
        library = root / "library"
        staging = root / "staging"
        state_path = root / "queue.json"
        organizer = Organizer()
        controller = ChaosController(
            organizer,
            self.plans,
            self.log,
            self.download_concurrency,
        )
        self.log.add(
            "campaign_started",
            version=CHAOS_VERSION,
            seed=self.seed,
            download_concurrency=self.download_concurrency,
            plan=[asdict(plan) for plan in self.plans],
        )

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(organizer_module.conf, "library_path", str(library))
            )
            stack.enter_context(
                patch.object(organizer_module.conf, "staging_path", str(staging))
            )
            stack.enter_context(
                patch.object(organizer_module.conf, "minimum_staging_free_bytes", 0)
            )
            stack.enter_context(
                patch.object(organizer_module.conf, "preserve_failed_staging", False)
            )
            stack.enter_context(
                patch(
                    "autodrome.models.download_job.uuid4",
                    side_effect=self._deterministic_job_id,
                )
            )
            stack.enter_context(
                patch(
                    "autodrome.models.download_job.utc_now",
                    side_effect=self._deterministic_timestamp,
                )
            )

            self.manager = self._new_manager(controller, state_path)
            try:
                for plan in self.plans:
                    job_id = await self.manager.enqueue(plan.payload)
                    self.log.add("job_enqueued", album=plan.album, job_id=job_id)

                self._arm_queue_fault(self.manager, controller)
                self.manager.start()
                for _ in range(2):
                    action, album = await controller.control_points.get()
                    if action == "running_cancel":
                        job = self._job_for_album(self.manager, album, "running")
                        status = await self.manager.cancel_job(job["job_id"])
                        self.log.add(
                            "running_cancel_requested",
                            album=album,
                            status=status,
                        )
                        await self._wait_for_status(
                            self.manager, job["job_id"], "cancelled"
                        )
                    elif action == "restart":
                        active = self._job_for_album(self.manager, album, "running")
                        await self.manager.stop()
                        self.log.add("worker_stopped", album=album)
                        interrupted = self._job_by_id(self.manager, active["job_id"])
                        if interrupted["status"] != "interrupted":
                            raise AssertionError(
                                "Restart control point did not preserve an interrupted job"
                            )
                        self.manager = self._new_manager(controller, state_path)
                        self._arm_queue_fault(self.manager, controller)
                        self.manager.start()
                        self.log.add("worker_restarted", album=album)
                    else:
                        raise AssertionError(f"Unknown chaos control action: {action}")
                    controller.control_points.task_done()

                await self.manager.queue.join()
                self.log.add("initial_queue_drained")

                retry_ids = []
                for job in list(self.manager.snapshot()):
                    if job["status"] in RETRYABLE_STATUSES:
                        retry_id = await self.manager.retry_job(job["job_id"])
                        retry_ids.append(retry_id)
                        self.log.add(
                            "recovery_retry_enqueued",
                            album=job["album"],
                            retry_of=job["job_id"],
                            job_id=retry_id,
                        )
                await self.manager.queue.join()
                self.log.add("recovery_queue_drained", retries=len(retry_ids))

                await self._assert_duplicate_protection(library)
                self._assert_invariants(library, state_path, controller)
                result = {
                    "result": "PASS",
                    "scenario": SCENARIO,
                    "seed": self.seed,
                    "chaos_version": CHAOS_VERSION,
                    "download_concurrency": self.download_concurrency,
                    "plan": [asdict(plan) for plan in self.plans],
                    "events": list(self.log.events),
                    "final_state": self.manager.snapshot(),
                    "status_counts": dict(
                        sorted(Counter(
                            job["status"] for job in self.manager.snapshot()
                        ).items())
                    ),
                }
                return result
            finally:
                if self.manager is not None:
                    await self.manager.stop()

    _job_id_counter = 0
    _timestamp_counter = 0

    def _deterministic_job_id(self):
        self._job_id_counter += 1
        return uuid5(
            NAMESPACE_URL,
            f"autodrome-chaos:{self.seed}:job:{self._job_id_counter}",
        )

    def _deterministic_timestamp(self) -> str:
        self._timestamp_counter += 1
        timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(
            milliseconds=self._timestamp_counter
        )
        return timestamp.isoformat()

    def _new_manager(
        self,
        controller: ChaosController,
        state_path: Path,
    ) -> DownloadQueueManager:
        manager = DownloadQueueManager(
            controller,
            NoopWebSocketManager(),
            str(state_path),
        )
        manager.STORAGE_RETRY_SECONDS = 0
        return manager

    def _arm_queue_fault(
        self,
        manager: DownloadQueueManager,
        controller: ChaosController,
    ) -> None:
        persist_state = manager._persist_state

        def persist_with_fault() -> None:
            target = next(
                (
                    job
                    for job in manager._jobs.values()
                    if job.status == "running"
                    and controller.plans[job.payload["album"]].kind
                    == "queue_write_failure"
                    and controller.attempts[job.payload["album"]] == 0
                ),
                None,
            )
            if target is not None and not self.queue_fault_injected:
                self.queue_fault_injected = True
                self.log.add(
                    "fault_injected",
                    album=target.payload["album"],
                    point="queue.persist.running",
                )
                self.queue_fault.hit("queue.persist.running")
            persist_state()

        manager._persist_state = persist_with_fault

    async def _wait_for_status(
        self,
        manager: DownloadQueueManager,
        job_id: str,
        expected: str,
    ) -> None:
        while self._job_by_id(manager, job_id)["status"] != expected:
            await asyncio.sleep(0)

    @staticmethod
    def _job_by_id(manager: DownloadQueueManager, job_id: str) -> dict[str, Any]:
        return next(job for job in manager.snapshot() if job["job_id"] == job_id)

    @staticmethod
    def _job_for_album(
        manager: DownloadQueueManager,
        album: str,
        status: str,
    ) -> dict[str, Any]:
        return next(
            job
            for job in manager.snapshot()
            if job["album"] == album and job["status"] == status
        )

    async def _assert_duplicate_protection(self, library: Path) -> None:
        assert self.manager is not None
        succeeded_albums = {
            job["album"]
            for job in self.manager.snapshot()
            if job["status"] == "succeeded"
        }
        before = self._library_fingerprints(library)
        job_count = len(self.manager.snapshot())
        for plan in self.plans:
            if plan.album not in succeeded_albums:
                continue
            try:
                await self.manager.enqueue(plan.payload)
            except FileExistsError:
                self.log.add("duplicate_blocked", album=plan.album)
            else:
                raise AssertionError(
                    f"Published album accepted a duplicate enqueue: {plan.album}"
                )
        if len(self.manager.snapshot()) != job_count:
            raise AssertionError("Duplicate preflight created phantom queue jobs")
        if self._library_fingerprints(library) != before:
            raise AssertionError("Duplicate preflight changed published library bytes")

    def _assert_invariants(
        self,
        library: Path,
        state_path: Path,
        controller: ChaosController,
    ) -> None:
        assert self.manager is not None
        snapshot = self.manager.snapshot()
        persisted = json.loads(state_path.read_text(encoding="utf-8"))["jobs"]
        expected_persisted = [
            job.to_storage_dict() for job in self.manager._jobs.values()
        ]
        if persisted != expected_persisted:
            raise AssertionError("Durable queue state differs from in-memory state")
        if self.manager.storage_error is not None:
            raise AssertionError("Campaign ended with uncertain durable queue state")
        if any(job["status"] not in TERMINAL_STATUSES for job in snapshot):
            raise AssertionError("Campaign ended with a non-terminal job")
        if any(
            job["status"] in RETRYABLE_STATUSES and not job.get("error")
            for job in snapshot
        ):
            raise AssertionError("Recoverable job lost its failure context")

        for plan in self.plans:
            album_jobs = [job for job in snapshot if job["album"] == plan.album]
            statuses = [job["status"] for job in album_jobs]
            destination = library / "Chaos Artist" / plan.album
            if plan.kind == "running_cancel":
                if statuses != ["cancelled"] or destination.exists():
                    raise AssertionError("Running cancellation published or lost its job")
                continue
            if "succeeded" not in statuses:
                raise AssertionError(f"No recovery path succeeded for {plan.album}")
            if plan.kind in {
                "provider_failure",
                "track_failure",
                "filesystem_failure",
            } and statuses != ["failed", "succeeded"]:
                raise AssertionError(f"Fault did not fail then recover for {plan.album}")
            if plan.kind == "restart" and statuses != ["interrupted", "succeeded"]:
                raise AssertionError(f"Restart did not interrupt then recover {plan.album}")
            if plan.kind in {"success", "queue_write_failure"} and statuses != [
                "succeeded"
            ]:
                raise AssertionError(f"Unexpected status sequence for {plan.album}")

            marker = destination / ".autodrome-chaos-complete.json"
            if not marker.is_file():
                raise AssertionError(f"Published album lacks validation marker: {plan.album}")
            metadata = json.loads(marker.read_text(encoding="utf-8"))
            tracks = sorted(destination.glob("*.mp3"))
            if (
                metadata.get("validated") is not True
                or metadata.get("track_count") != plan.track_count
                or len(tracks) != plan.track_count
                or any(not track.read_bytes() for track in tracks)
            ):
                raise AssertionError(f"Partial or invalid album was published: {plan.album}")

        provider_plan = next(
            plan for plan in self.plans if plan.kind == "provider_failure"
        )
        provider_failure = next(
            job
            for job in snapshot
            if job["album"] == provider_plan.album and job["status"] == "failed"
        )
        if "MusicBrainz failed" not in provider_failure["error"]:
            raise AssertionError("Upstream failure was converted into an empty success")

        retryable_ids = {
            job["job_id"]
            for job in snapshot
            if job["status"] in RETRYABLE_STATUSES
        }
        recovered_ids = {
            job["retry_of"]
            for job in snapshot
            if job["status"] == "succeeded" and job.get("retry_of")
        }
        if retryable_ids != recovered_ids:
            raise AssertionError("A failed/interrupted job has no coherent recovery")

        controller.assert_faults_reached()
        self.queue_fault.assert_complete()

    @staticmethod
    def _library_fingerprints(library: Path) -> dict[str, str]:
        if not library.exists():
            return {}
        fingerprints = {}
        for path in sorted(candidate for candidate in library.rglob("*") if candidate.is_file()):
            relative = str(path.relative_to(library))
            fingerprints[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        return fingerprints


async def run_chaos(
    seed: int,
    *,
    max_events: int = 160,
    timeout_seconds: float = 10,
) -> dict[str, Any]:
    """Run one bounded campaign and wrap failures with replay diagnostics."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    campaign = ChaosCampaign(seed, max_events)
    try:
        with TemporaryDirectory(prefix="autodrome-chaos-") as directory:
            async with asyncio.timeout(timeout_seconds):
                return await campaign.run(Path(directory))
    except ChaosFailure:
        raise
    except Exception as error:
        last_state = (
            campaign.manager.snapshot() if campaign.manager is not None else []
        )
        raise ChaosFailure(
            seed=seed,
            reason=f"{type(error).__name__}: {error}",
            events=list(campaign.log.events),
            last_state=last_state,
        ) from error
