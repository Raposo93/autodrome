import asyncio
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from autodrome.services.ytdlp_runtime import (
    UnsupportedDenoVersion,
    js_runtime_options,
    read_deno_version,
    resolve_deno_executable,
)


def test_default_policy_enables_only_deno_without_inventing_a_path():
    first = js_runtime_options(None)
    second = js_runtime_options(None)

    assert first == {"js_runtimes": {"deno": {}}}
    assert second == first
    assert second is not first


def test_explicit_directory_is_resolved_to_its_executable(tmp_path):
    executable = tmp_path / "deno"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)

    assert resolve_deno_executable(str(tmp_path)) == str(executable)


def test_path_lookup_uses_the_service_environment_not_an_interactive_home():
    service_path = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
    with patch.dict(os.environ, {"PATH": service_path}, clear=True), patch(
        "autodrome.services.ytdlp_runtime.shutil.which",
        return_value=None,
    ) as which:
        with pytest.raises(FileNotFoundError):
            resolve_deno_executable(None)

    which.assert_called_once_with("deno")
    assert "/home/" not in service_path


def test_version_check_accepts_supported_deno_output(tmp_path):
    executable = tmp_path / "deno"
    executable.write_text(
        "#!/bin/sh\nprintf 'deno 2.9.5 (stable, release, test)\\n'\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)

    assert asyncio.run(read_deno_version(str(executable), timeout=1)) == "deno 2.9.5"


def test_version_check_rejects_deno_below_supported_minimum(tmp_path):
    executable = Path(tmp_path) / "deno"
    executable.write_text("#!/bin/sh\nprintf 'deno 2.2.9\\n'\n", encoding="utf-8")
    executable.chmod(0o700)

    with pytest.raises(UnsupportedDenoVersion, match="2.3.0"):
        asyncio.run(read_deno_version(str(executable), timeout=1))
