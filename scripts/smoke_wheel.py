#!/usr/bin/env python3
"""Install a wheel away from the checkout and smoke its production command."""

import json
import os
import site
import socket
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.request
import venv
import zipfile
from contextlib import contextmanager
from pathlib import Path


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_for_response(url: str, process: subprocess.Popen, timeout: float) -> bytes:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output, _ = process.communicate()
            raise RuntimeError(
                f"Installed Autodrome exited with {process.returncode}:\n{output}"
            )
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return response.read()
        except (urllib.error.URLError, TimeoutError) as error:
            last_error = error
            time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


@contextmanager
def read_only_installation(directory: Path):
    """Protect installed files, including the old site-packages/covers location."""
    original_modes = []
    try:
        for path in [directory, *directory.rglob("*")]:
            if path.is_symlink():
                continue
            mode = stat.S_IMODE(path.stat().st_mode)
            original_modes.append((path, mode))
            path.chmod(mode & ~0o222)
        yield
    finally:
        for path, mode in original_modes:
            path.chmod(mode)


def smoke(wheel: Path, *, install_dependencies: bool = False) -> None:
    if not wheel.is_file():
        raise SystemExit(f"Wheel does not exist: {wheel}")
    if os.geteuid() == 0:
        raise RuntimeError(
            "Run the wheel smoke as a non-root user so read-only installation "
            "permissions are enforced"
        )
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        if "autodrome/static/index.html" not in names:
            raise RuntimeError("Wheel does not contain the compiled frontend")
        static_assets = [
            f"/{name.removeprefix('autodrome/static/')}"
            for name in names
            if name.startswith("autodrome/static/assets/")
            and name.endswith((".css", ".js"))
        ]
        if not static_assets:
            raise RuntimeError("Wheel does not contain compiled frontend assets")
        entry_points = next(
            (
                name
                for name in names
                if name.endswith(".dist-info/entry_points.txt")
            ),
            None,
        )
        if entry_points is None or (
            b"autodrome = autodrome.server:main"
            not in archive.read(entry_points)
        ):
            raise RuntimeError("Wheel does not define the autodrome command")

    with tempfile.TemporaryDirectory(prefix="autodrome-wheel-smoke-") as directory:
        root = Path(directory)
        environment = root / "venv"
        runtime = root / "runtime"
        library = runtime / "library"
        runtime.mkdir()
        library.mkdir()

        venv.EnvBuilder(
            with_pip=True,
        ).create(environment)
        python = environment / "bin" / "python"
        command = environment / "bin" / "autodrome"
        install_command = [python, "-m", "pip", "install"]
        if not install_dependencies:
            install_command.append("--no-deps")
        install_command.append(str(wheel.resolve()))
        install_environment = os.environ.copy()
        install_environment["PIP_CACHE_DIR"] = str(root / "pip-cache")
        subprocess.run(
            install_command,
            check=True,
            env=install_environment,
        )

        installed_packages = Path(subprocess.check_output(
            [python, "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            text=True,
        ).strip())
        child_environment = os.environ.copy()
        if install_dependencies:
            child_environment.pop("PYTHONPATH", None)
        else:
            # Shared dependencies must not shadow the wheel under test.
            child_environment["PYTHONPATH"] = os.pathsep.join(
                [str(installed_packages), *site.getsitepackages()]
            )
        child_environment.pop("VERSION", None)
        port = available_port()
        child_environment.update(
            {
                "GOOGLE_API_KEY": "wheel-smoke-key",
                "CONTACT_EMAIL": "wheel-smoke@example.test",
                "LIBRARY_PATH": str(library),
                "COVER_ART_CACHE_PATH": str(runtime / "cover-cache"),
                "PYTHONDONTWRITEBYTECODE": "1",
                "API_HOST": "127.0.0.1",
                "API_PORT": str(port),
            }
        )

        with read_only_installation(installed_packages):
            check_installation(
                python, command, runtime, child_environment, port, static_assets
            )


def check_installation(
    python: Path,
    command: Path,
    runtime: Path,
    child_environment: dict,
    port: int,
    static_assets: list[str],
) -> None:
    version_output = subprocess.check_output(
        [
            python,
            "-c",
            textwrap.dedent("""\
                import asyncio
                import os
                import sys
                from importlib.metadata import version
                from pathlib import Path
                from unittest.mock import AsyncMock

                import autodrome
                from autodrome.config import Config
                from autodrome.metadata_service import MetadataService
                from autodrome.web import app

                package = Path(autodrome.__file__).resolve().parent
                assert package.is_relative_to(Path(sys.prefix).resolve()), package
                assert not os.access(package, os.W_OK), package
                assert not os.access(package.parent, os.W_OK), package.parent
                settings = Config()
                release_id = "b9aee635-503d-4231-a074-4ff7ac273dde"
                content = b"controlled CAA smoke content"
                http_client = AsyncMock()
                http_client.get_binary.return_value = content
                service = MetadataService(
                    http_client=http_client,
                    cover_art_cache_path=settings.cover_art_cache_path,
                )
                cover = Path(asyncio.run(service.get_cover_art(release_id)))
                assert cover == Path(settings.cover_art_cache_path) / f"{release_id}.jpg"
                assert cover.read_bytes() == content
                assert asyncio.run(service.get_cover_art(release_id)) == str(cover)
                http_client.get_binary.assert_awaited_once_with(
                    f"https://coverartarchive.org/release/{release_id}/front",
                    provider="Cover Art Archive",
                    context=f"downloading front cover for release {release_id}",
                )
                assert version("yt-dlp-ejs")
                assert str(app.url_path_for("websocket_endpoint")) == "/ws"
                print(version("autodrome"))
                print(settings.version)
            """),
        ],
        cwd=runtime,
        env=child_environment,
        text=True,
    ).splitlines()
    if (
        len(version_output) != 2
        or version_output[1] != f"autodrome/{version_output[0]}"
    ):
        raise RuntimeError(f"Unexpected installed version: {version_output}")

    process = subprocess.Popen(
        [command],
        cwd=runtime,
        env=child_environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        auth = json.loads(wait_for_response(
            f"{base_url}/api/auth", process, timeout=15
        ))
        if auth != {"authenticated": True}:
            raise RuntimeError(f"Unexpected API response: {auth}")
        index = wait_for_response(f"{base_url}/", process, timeout=5)
        if b'<div id="app"></div>' not in index:
            raise RuntimeError("Installed frontend did not serve index.html")
        for asset in static_assets:
            if not wait_for_response(f"{base_url}{asset}", process, timeout=5):
                raise RuntimeError(f"Installed frontend asset is empty: {asset}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main() -> None:
    arguments = sys.argv[1:]
    install_dependencies = False
    if "--install-dependencies" in arguments:
        arguments.remove("--install-dependencies")
        install_dependencies = True
    if len(arguments) != 1:
        raise SystemExit(
            "Usage: smoke_wheel.py [--install-dependencies] PATH_TO_WHEEL"
        )
    smoke(Path(arguments[0]), install_dependencies=install_dependencies)


if __name__ == "__main__":
    main()
