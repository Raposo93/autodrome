import os
import tempfile
import unittest

from autodrome.path_safety import resolve_album_path
from autodrome.services.organizer import Organizer


class TestPathSafety(unittest.TestCase):
    def test_resolved_album_stays_below_library(self):
        with tempfile.TemporaryDirectory() as library:
            destination = resolve_album_path(library, "Artist", "Album")

            self.assertEqual(destination, destination.resolve())
            self.assertEqual(destination.parent.parent, destination.parent.parent.resolve())
            self.assertTrue(str(destination).startswith(os.path.abspath(library)))

    def test_organizer_rejects_parent_components(self):
        organizer = Organizer()

        with self.assertRaisesRegex(ValueError, "Path component"):
            organizer._get_album_folder("..", "Album")

    def test_resolver_rejects_escape_through_existing_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            library = os.path.join(root, "library")
            outside = os.path.join(root, "outside")
            os.makedirs(library)
            os.makedirs(outside)
            os.symlink(outside, os.path.join(library, "Artist"))

            with self.assertRaisesRegex(ValueError, "escapes"):
                resolve_album_path(library, "Artist", "Album")


if __name__ == "__main__":
    unittest.main()
