from pathlib import Path, PurePosixPath, PureWindowsPath


def validate_path_component(value: str) -> str:
    component = value.strip()
    if not component or component in {".", ".."}:
        raise ValueError("Path component cannot be empty, '.' or '..'")
    if "\x00" in component:
        raise ValueError("Path component cannot contain null bytes")
    if PurePosixPath(component).is_absolute() or PureWindowsPath(component).is_absolute():
        raise ValueError("Absolute paths are not allowed")
    return component


def resolve_album_path(library_root: str, artist: str, album: str) -> Path:
    root = Path(library_root).resolve()
    destination = (root / artist / album).resolve()
    try:
        destination.relative_to(root)
    except ValueError as e:
        raise ValueError("Album destination escapes the configured library") from e
    if destination == root:
        raise ValueError("Album destination must be below the configured library")
    return destination
