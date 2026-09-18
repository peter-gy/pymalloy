"""Reject ambiguous native file lookup without changing DuckDB resolution."""

from collections.abc import Mapping
from pathlib import Path


def check_files(files: Mapping[str, Path]) -> None:
    for alias, expected in files.items():
        shadow = Path(alias)
        if (
            not shadow.is_absolute()
            and shadow.is_file()
            and shadow.resolve() != expected.resolve()
        ):
            raise ValueError(
                f"Relative file {alias!r} is shadowed by the current directory. "
                "Use an absolute file path or run from a directory without that file."
            )


def file_config(
    files: Mapping[str, Path], remote_files: tuple[str, ...] = ()
) -> dict[str, object]:
    """Configure local input access and optional HTTP(S) readers."""
    config: dict[str, object] = {
        "allowed_paths": sorted(
            {
                value
                for alias, path in files.items()
                for value in (alias, str(path.resolve()))
            }
        ),
        "enable_external_access": False,
    }
    if remote_files:
        config["allowed_directories"] = ["http://", "https://"]
    return config
