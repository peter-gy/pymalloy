"""Publish complete model source while detecting previously observed file edits."""

import os
import stat
from pathlib import Path
from uuid import uuid4


def write_text(
    path: Path,
    text: str,
    *,
    expected: str | None = None,
    overwrite: bool = False,
) -> Path:
    """Publish UTF-8 text atomically and retain an existing file's permissions.

    An expected revision must match the current text, including line endings.
    This check detects prior edits; it does not lock out concurrent writers
    between checking and replacing the file. Parent directories must exist.
    """
    target = path.resolve()
    temporary = target.parent / f".malloy-{uuid4().hex}"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(text.encode("utf-8"))

        if expected is not None:
            try:
                with target.open(encoding="utf-8", newline="") as handle:
                    current = handle.read()
                    mode = stat.S_IMODE(os.fstat(handle.fileno()).st_mode)
            except FileNotFoundError:
                raise ValueError(
                    "Model changed on disk. Load it again before saving."
                ) from None
            if current != expected:
                raise ValueError("Model changed on disk. Load it again before saving.")
            temporary.chmod(mode)
            os.replace(temporary, target)
        elif overwrite:
            try:
                mode = stat.S_IMODE(target.stat().st_mode)
            except FileNotFoundError:
                pass
            else:
                temporary.chmod(mode)
            os.replace(temporary, target)
        else:
            os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
