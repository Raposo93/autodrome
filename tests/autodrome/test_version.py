from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

from autodrome.version import build_commit, default_runtime_version, installed_version


def test_installed_distribution_version_is_used():
    with patch("autodrome.version.version", return_value="0.2.0"):
        assert installed_version() == "0.2.0"
        assert default_runtime_version() == "autodrome/0.2.0"


def test_source_tree_without_distribution_has_no_invented_version():
    with patch(
        "autodrome.version.version",
        side_effect=PackageNotFoundError("autodrome"),
    ):
        assert installed_version() is None
        assert default_runtime_version() is None


def test_build_commit_accepts_only_a_hexadecimal_identifier():
    with patch.dict("os.environ", {"AUTODROME_COMMIT": "ABCDEF123"}, clear=True):
        assert build_commit() == "abcdef123"
    with patch.dict("os.environ", {"AUTODROME_COMMIT": "not-a-commit"}, clear=True):
        assert build_commit() is None
