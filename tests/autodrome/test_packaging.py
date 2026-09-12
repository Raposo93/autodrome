import runpy
from unittest.mock import patch

import pytest
from setuptools.errors import SetupError


def load_build_helpers():
    with patch("setuptools.setup"):
        return runpy.run_path("setup.py")


def test_build_fails_clearly_without_compiled_frontend(tmp_path):
    helpers = load_build_helpers()
    helpers["require_frontend"].__globals__["FRONTEND_DIST"] = tmp_path

    with pytest.raises(SetupError, match="Compiled frontend missing"):
        helpers["require_frontend"]()
