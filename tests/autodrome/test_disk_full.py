import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from autodrome.controllers.downloader_controller import DownloaderController
from autodrome.models.release import Release
from autodrome.models.track import Track
from autodrome.services import organizer as organizer_module
from autodrome.services.cover_embedder import CoverEmbedder, PreparedCover
from autodrome.services.download_queue import DownloadQueueManager
from autodrome.services.organizer import Organizer
from autodrome.services.tagger import Tagger
from autodrome.yt_downloader import TrackDownloadError, YTDownloader
from tests.fault_injection import FaultInjector, NoSpaceError


PAYLOAD = {
    "playlist_url": "https://example.test/playlist",
    "artist": "Artist",
    "album": "Album",
    "release_id": "release-1",
    "track_count": 1,
}

DISK_FULL_PHASES = {
    "download.track.write": "downloading",
    "yt_dlp.postprocess.ffmpeg": "downloading",
    "tagger.audio.save": "tagging",
    "cover_embedder.audio.save": "tagging",
    "organizer.publish.rename": "publishing",
}


class TestDiskFullFilesystemFlow(unittest.IsolatedAsyncioTestCase):
    async def exercise_phase(self, point, *, preserve_failed_staging):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            library = root_path / "library"
            staging = root_path / "staging"
            state_path = root_path / "queue.json"
            existing_album = library / "Existing Artist" / "Existing Album"
            existing_album.mkdir(parents=True)
            existing_track = existing_album / "01 - Existing.mp3"
            existing_track.write_bytes(b"valid library content")
            cover_path = root_path / "cover.jpg"
            cover_path.write_bytes(b"fixture cover")

            faults = FaultInjector(
                f"disk-full-{point}",
                {point: {1: NoSpaceError}},
            )
            downloader = MagicMock()

            async def download_playlist(url, destination, total, progress, **kwargs):
                await progress("manifest", None, None, None)
                await progress("downloading", 1, total, 0)
                destination_path = Path(destination)
                if point == "download.track.write":
                    (destination_path / "01 - Source.part").write_bytes(b"partial")
                    faults.hit(point)
                if point == "yt_dlp.postprocess.ffmpeg":
                    (destination_path / "01 - Source.webm").write_bytes(b"source")
                    faults.hit(point)
                (destination_path / "01 - Source.mp3").write_bytes(b"ID3")
                await progress("downloading", 1, total, 1)

            downloader.download_playlist = AsyncMock(side_effect=download_playlist)
            metadata = MagicMock()
            metadata.get_release = AsyncMock(
                return_value=Release(
                    release_id="release-1",
                    title="Album",
                    date="2026",
                    artist="Artist",
                    cover_url=None,
                    tracks=[Track(1, "Track")],
                )
            )
            metadata.get_cover_art = AsyncMock(
                return_value=(
                    str(cover_path)
                    if point == "cover_embedder.audio.save"
                    else None
                )
            )

            organizer = Organizer()
            if point == "tagger.audio.save":
                organizer.tagger.tag_files = MagicMock(
                    side_effect=lambda *args: faults.hit(point)
                )
            else:
                organizer.tagger.tag_files = MagicMock()
            organizer.validate_album = MagicMock()
            organizer.cover_embedder.prepare_cover = MagicMock(return_value=object())
            if point == "cover_embedder.audio.save":
                organizer.cover_embedder.embed_cover = MagicMock(
                    side_effect=lambda *args: faults.hit(point)
                )
            else:
                organizer.cover_embedder.embed_cover = MagicMock()

            controller = DownloaderController(downloader, organizer, metadata)
            manager = DownloadQueueManager(controller, AsyncMock(), str(state_path))
            real_rename = os.rename
            album_path = library / "Artist" / "Album"

            def rename_with_fault(source, destination):
                if Path(destination) == album_path:
                    faults.hit("organizer.publish.rename")
                real_rename(source, destination)

            disk_usage = MagicMock(return_value=MagicMock(free=2_048))
            try:
                with (
                    patch.multiple(
                        organizer_module.conf,
                        library_path=str(library),
                        staging_path=str(staging),
                        minimum_staging_free_bytes=1_024,
                        preserve_failed_staging=preserve_failed_staging,
                    ),
                    patch(
                        "autodrome.services.organizer.shutil.disk_usage",
                        disk_usage,
                    ),
                    patch(
                        "autodrome.services.organizer.os.rename",
                        side_effect=rename_with_fault,
                    ),
                ):
                    job_id = await manager.enqueue(PAYLOAD)
                    manager.start()
                    await asyncio.wait_for(manager.queue.join(), timeout=1)

                faults.assert_complete()
                job = manager._jobs[job_id]
                self.assertEqual(job.status, "failed")
                self.assertIn("Errno 28", job.error)
                self.assertIn(point, job.error)
                self.assertEqual(job.progress["phase"], DISK_FULL_PHASES[point])
                self.assertIsNone(manager.storage_error)
                self.assertFalse(album_path.exists())
                self.assertEqual(existing_track.read_bytes(), b"valid library content")
                disk_usage.assert_called_once_with(str(staging.resolve()))

                with state_path.open(encoding="utf-8") as state_file:
                    persisted = json.load(state_file)["jobs"][0]
                self.assertEqual(persisted["status"], "failed")
                self.assertEqual(persisted["error"], job.error)
                self.assertEqual(
                    persisted["progress"]["phase"],
                    DISK_FULL_PHASES[point],
                )

                staged_albums = list(staging.glob("album-*"))
                if preserve_failed_staging:
                    self.assertEqual(len(staged_albums), 1)
                    self.assertTrue(any(staged_albums[0].iterdir()))
                else:
                    self.assertEqual(staged_albums, [])
            finally:
                await manager.stop()

    async def test_enospc_after_successful_space_check_never_publishes(self):
        for point in DISK_FULL_PHASES:
            with self.subTest(point=point):
                await self.exercise_phase(point, preserve_failed_staging=True)

    async def test_cleanup_policy_removes_failed_staging_only(self):
        await self.exercise_phase(
            "tagger.audio.save",
            preserve_failed_staging=False,
        )

    async def test_recovery_refuses_to_overwrite_an_album_that_now_exists(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            library = root_path / "library"
            staging = root_path / "staging"
            organizer = Organizer()
            faults = FaultInjector(
                "disk-full-recovery-existing-album",
                {"download.track.write": {1: NoSpaceError}},
            )

            with (
                patch.multiple(
                    organizer_module.conf,
                    library_path=str(library),
                    staging_path=str(staging),
                    minimum_staging_free_bytes=0,
                    preserve_failed_staging=True,
                ),
            ):
                failed_staging = None
                with self.assertRaisesRegex(OSError, "download.track.write"):
                    with organizer.create_staging_folder(
                        "Artist", "Album"
                    ) as failed_staging:
                        (Path(failed_staging) / "01 - Source.part").write_bytes(
                            b"partial"
                        )
                        faults.hit("download.track.write")

                album_path = library / "Artist" / "Album"
                album_path.mkdir(parents=True)
                valid_track = album_path / "01 - Existing.mp3"
                valid_track.write_bytes(b"published elsewhere")

                with self.assertRaisesRegex(FileExistsError, "Album already exists"):
                    with organizer.create_staging_folder("Artist", "Album"):
                        pass

            faults.assert_complete()
            self.assertEqual(valid_track.read_bytes(), b"published elsewhere")
            self.assertTrue(
                (Path(failed_staging) / "01 - Source.part").is_file()
            )


class TestDiskFullServiceBoundaries(unittest.IsolatedAsyncioTestCase):
    async def test_yt_dlp_download_and_postprocess_enospc_keep_phase_context(self):
        for point, leftover in (
            ("download.track.write", "01 - Source.part"),
            ("yt_dlp.postprocess.ffmpeg", "01 - Source.webm"),
        ):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as directory:
                faults = FaultInjector(
                    f"service-{point}",
                    {point: {1: NoSpaceError}},
                )
                ydl = MagicMock()

                def fail_download(urls):
                    (Path(directory) / leftover).write_bytes(b"partial")
                    faults.hit(point)

                ydl.download.side_effect = fail_download
                downloader = YTDownloader(track_download_attempts=1)
                with (
                    patch("autodrome.yt_downloader.YoutubeDL") as youtube_dl,
                    patch(
                        "autodrome.yt_downloader.asyncio.to_thread",
                        new_callable=AsyncMock,
                    ) as to_thread,
                ):
                    youtube_dl.return_value.__enter__.return_value = ydl
                    to_thread.side_effect = lambda function, *args: function(*args)
                    with self.assertRaises(TrackDownloadError) as raised:
                        await downloader.download_track(
                            "https://youtube.test/track-1",
                            directory,
                            1,
                            MagicMock(),
                        )

                faults.assert_complete()
                self.assertIn("Errno 28", raised.exception.reason)
                self.assertIn(point, raised.exception.reason)
                self.assertTrue((Path(directory) / leftover).is_file())

    async def test_tag_and_cover_save_propagate_enospc(self):
        track = Track(1, "Track")
        for point in ("tagger.audio.save", "cover_embedder.audio.save"):
            with self.subTest(point=point):
                faults = FaultInjector(
                    f"service-{point}",
                    {point: {1: NoSpaceError}},
                )
                audio = MagicMock()
                audio.tags = MagicMock()
                audio.save.side_effect = lambda: faults.hit(point)

                if point == "tagger.audio.save":
                    with (
                        patch(
                            "autodrome.services.tagger.os.listdir",
                            return_value=["01 - Track.mp3"],
                        ),
                        patch(
                            "autodrome.services.tagger.MP3",
                            return_value=audio,
                        ),
                    ):
                        with self.assertRaisesRegex(OSError, "tagger.audio.save"):
                            Tagger().tag_files("/unused", "Artist", "Album", [track])
                else:
                    cover = PreparedCover(
                        data=b"cover",
                        mime_type="image/jpeg",
                        original_size=5,
                        dimensions=(1, 1),
                        optimized=False,
                    )
                    with patch(
                        "autodrome.services.cover_embedder.MP3",
                        return_value=audio,
                    ):
                        with self.assertRaisesRegex(
                            OSError, "cover_embedder.audio.save"
                        ):
                            CoverEmbedder(max_bytes=10).embed_cover(
                                "/unused/01 - Track.mp3",
                                cover,
                            )

                faults.assert_complete()
