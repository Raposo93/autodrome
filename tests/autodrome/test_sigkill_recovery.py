import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TestSigkillRecovery(unittest.TestCase):
    def kill_at_synchronized_point(self, scenario: str, root: Path) -> None:
        ready_read, ready_write = os.pipe()
        hold_read, hold_write = os.pipe()
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.processes.crash_worker",
                scenario,
                str(root),
                "--ready-fd",
                str(ready_write),
                "--hold-fd",
                str(hold_read),
            ],
            cwd=PROJECT_ROOT,
            pass_fds=(ready_write, hold_read),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        os.close(ready_write)
        os.close(hold_read)
        try:
            readable, _, _ = select.select([ready_read], [], [], 5)
            if not readable:
                process.kill()
                stdout, stderr = process.communicate(timeout=5)
                self.fail(
                    f"Scenario '{scenario}' never reached its kill point. "
                    f"stdout={stdout!r}, stderr={stderr!r}"
                )
            event = os.read(ready_read, 128).decode().strip()
            self.assertEqual(event, scenario)
            self.assertIsNone(process.poll())

            process.kill()
            process.communicate(timeout=5)
            self.assertEqual(process.returncode, -signal.SIGKILL)
        finally:
            os.close(ready_read)
            os.close(hold_write)
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)

    def recover_in_new_process(self, root: Path):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.processes.crash_worker",
                "recover",
                str(root),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"Recovery failed: stdout={result.stdout!r}, stderr={result.stderr!r}",
        )
        return json.loads(
            (root / "recovery-snapshot.json").read_text(encoding="utf-8")
        )

    def test_sigkill_during_download_preserves_partial_staging_and_queue_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.kill_at_synchronized_point("during_download", root)

            persisted_before_restart = json.loads(
                (root / "queue.json").read_text(encoding="utf-8")
            )["jobs"]
            self.assertEqual(
                [job["status"] for job in persisted_before_restart],
                ["running", "queued"],
            )
            staged_albums = list((root / "staging").glob("album-*"))
            self.assertEqual(len(staged_albums), 1)
            self.assertEqual(
                (staged_albums[0] / "01 - Source.part").read_bytes(),
                b"partial audio",
            )
            self.assertFalse((root / "library" / "Artist" / "Album").exists())

            recovered = self.recover_in_new_process(root)

            self.assertEqual(
                [job["status"] for job in recovered],
                ["interrupted", "succeeded"],
            )
            self.assertIn("restarted", recovered[0]["error"])
            self.assertEqual(
                json.loads(
                    (root / "recovery-calls.json").read_text(encoding="utf-8")
                ),
                ["Queued Album"],
            )
            self.assertTrue((staged_albums[0] / "01 - Source.part").is_file())
            self.assertFalse((root / "library" / "Artist" / "Album").exists())

    def test_sigkill_after_publish_does_not_repeat_or_overwrite_album(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.kill_at_synchronized_point("after_publish", root)

            album_path = root / "library" / "Artist" / "Album"
            published_track = album_path / "01 - Track.mp3"
            self.assertEqual(published_track.read_bytes(), b"ID3")
            self.assertEqual(
                [
                    job["status"]
                    for job in json.loads(
                        (root / "queue.json").read_text(encoding="utf-8")
                    )["jobs"]
                ],
                ["running", "queued"],
            )
            self.assertEqual(list((root / "staging").glob("album-*")), [])

            recovered = self.recover_in_new_process(root)

            self.assertEqual(
                [job["status"] for job in recovered],
                ["interrupted", "succeeded"],
            )
            self.assertEqual(
                json.loads(
                    (root / "recovery-calls.json").read_text(encoding="utf-8")
                ),
                ["Queued Album"],
            )
            self.assertEqual(published_track.read_bytes(), b"ID3")
