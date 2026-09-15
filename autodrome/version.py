"""Installed distribution version lookup with a source-tree fallback."""

import os
from importlib.metadata import PackageNotFoundError, version
from typing import Optional


def installed_version() -> Optional[str]:
    try:
        return version("autodrome")
    except PackageNotFoundError:
        return None


def default_runtime_version() -> Optional[str]:
    package_version = installed_version()
    return f"autodrome/{package_version}" if package_version else None


def build_commit() -> Optional[str]:
    for variable in ("AUTODROME_COMMIT", "GIT_COMMIT"):
        value = os.getenv(variable, "").strip().lower()
        if 7 <= len(value) <= 40 and all(
            character in "0123456789abcdef" for character in value
        ):
            return value
    return None
