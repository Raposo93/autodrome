"""Installed distribution version lookup with a source-tree fallback."""

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
