"""Build hooks that place the compiled frontend inside the Python package."""

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist
from setuptools.errors import SetupError


ROOT = Path(__file__).resolve().parent
FRONTEND_DIST = ROOT / "frontend" / "dist"


def require_frontend() -> Path:
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        raise SetupError(
            "Compiled frontend missing: run `npm ci --prefix frontend && "
            "npm run build --prefix frontend` before building Autodrome."
        )
    return FRONTEND_DIST


class BuildWithFrontend(build_py):
    def run(self) -> None:
        source = require_frontend()
        super().run()
        destination = Path(self.build_lib) / "autodrome" / "static"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)


class SourceWithFrontend(sdist):
    def run(self) -> None:
        require_frontend()
        super().run()


setup(cmdclass={"build_py": BuildWithFrontend, "sdist": SourceWithFrontend})
