"""Shared yt-dlp JavaScript runtime policy and local Deno detection."""

import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import Optional


DENO_MINIMUM_VERSION = (2, 3, 0)
DENO_MINIMUM_VERSION_TEXT = ".".join(map(str, DENO_MINIMUM_VERSION))


class UnsupportedDenoVersion(RuntimeError):
    def __init__(self, version: str) -> None:
        self.version = version
        super().__init__(
            f"Deno {version} is older than the supported minimum "
            f"{DENO_MINIMUM_VERSION_TEXT}"
        )


def js_runtime_options(deno_path: Optional[str]) -> dict:
    """Return a fresh yt-dlp option using Autodrome's single runtime policy."""
    config = {"path": deno_path} if deno_path else {}
    return {"js_runtimes": {"deno": config}}


def resolve_deno_executable(deno_path: Optional[str]) -> str:
    """Resolve Deno exactly from explicit config or the current process PATH."""
    if deno_path:
        candidate = Path(deno_path)
        if candidate.is_dir():
            candidate /= "deno"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        raise FileNotFoundError("deno")

    executable = shutil.which("deno")
    if executable is None:
        raise FileNotFoundError("deno")
    return executable


async def read_deno_version(deno_path: Optional[str], timeout: float) -> str:
    executable = resolve_deno_executable(deno_path)
    process = await asyncio.create_subprocess_exec(
        executable,
        "--version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    if process.returncode != 0:
        raise RuntimeError("Deno exited unsuccessfully")

    first_line = output.decode("utf-8", errors="replace").splitlines()[0:1]
    match = (
        re.match(r"deno\s+(\d+)\.(\d+)\.(\d+)(?:\S*)?", first_line[0])
        if first_line
        else None
    )
    if match is None:
        raise RuntimeError("Deno returned an unrecognized version")
    version = ".".join(match.groups())
    if tuple(map(int, match.groups())) < DENO_MINIMUM_VERSION:
        raise UnsupportedDenoVersion(version)
    return f"deno {version}"
