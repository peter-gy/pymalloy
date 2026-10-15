"""Native DuckDB settings and relative-file ambiguity checks."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def settings(
    data_root: str | Path | None = None,
    files: Mapping[str, Path] | None = None,
    remote_files: Sequence[str] = (),
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    values = {name.lower(): value for name, value in (config or {}).items()}
    if data_root is not None and "file_search_path" in values:
        raise ValueError("Choose data_root or config['file_search_path']")
    if "file_search_path" not in values:
        root = Path(data_root or Path.cwd()).resolve()
        if not root.is_dir():
            raise ValueError(f"Data directory does not exist: {root}")
        values["file_search_path"] = str(root)
    values.setdefault("timezone", "UTC")
    if files is not None:
        values.update(
            allowed_paths=sorted(
                {
                    value
                    for alias, path in files.items()
                    for value in (alias, str(path.resolve()))
                }
            ),
        )
        if remote_files:
            values["allowed_directories"] = ["http://", "https://"]
        values["enable_external_access"] = False
    return values


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
