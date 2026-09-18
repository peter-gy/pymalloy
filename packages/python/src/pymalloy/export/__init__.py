from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pymalloy._connection import DEFAULT_CONNECTION
from pymalloy._document import Document, Markdown, Profile, QueryCell
from pymalloy._errors import CompilationError, SchemaError
from pymalloy._selection import query_names
from pymalloy.export._bundle import SourceBundle, bundle

__all__ = [
    "Document",
    "Markdown",
    "Profile",
    "QueryCell",
    "SourceBundle",
    "bundle",
    "prepare",
]


def prepare(
    model: str | Path,
    *,
    profile: Profile | str = Profile.PRECOMPILED,
    connection_name: str = DEFAULT_CONNECTION,
    queries: Sequence[str] | None = None,
    all: bool = False,
    givens: Mapping[str, Any] | None = None,
    data_root: str | Path | None = None,
    database: str | Path | None = None,
    title: str | None = None,
    timeout: float = 120,
    files: Mapping[str, str | Path] | None = None,
    remote_files: Sequence[str] = (),
    extensions: Sequence[str] = (),
) -> Document:
    """Prepare notebook cells with explicit local and remote SQL reader inputs.

    Malloy table references are discovered. Declare opaque SQL reader inputs with
    files= for local aliases or remote_files= for HTTP(S) URLs.
    """
    from pymalloy.export._compile import compile_document

    path = Path(model).resolve()
    root = Path(data_root).resolve() if data_root is not None else path.parent
    selected = query_names(queries, all=all)
    db = Path(database).resolve() if database is not None else None
    if files is not None and not isinstance(files, Mapping):
        raise TypeError("files must be a mapping of aliases to paths")
    try:
        return compile_document(
            path,
            queries=selected,
            all=all,
            givens=givens,
            data_root=root,
            database=db,
            timeout=timeout,
            profile=Profile(profile),
            connection_name=connection_name,
            remote_files=remote_files,
            extensions=extensions,
            title=title if title is not None else path.stem.replace("_", " ").title(),
            files={
                name: Path(value).resolve() for name, value in (files or {}).items()
            },
        )
    except (CompilationError, SchemaError) as error:
        import duckdb

        cause = error
        while cause is not None:
            if isinstance(cause, duckdb.PermissionException):
                error.add_note(
                    "Native notebook file access is limited to declared inputs. "
                    "Declare local SQL reader inputs with files= and remote HTTP(S) readers with remote_files= "
                    "or use the widget profile."
                )
                break
            cause = cause.__cause__
        raise
