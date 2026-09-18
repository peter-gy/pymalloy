from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pymalloy._document import Document, Markdown, Profile, Query
from pymalloy._selection import query_names

__all__ = ["Document", "Markdown", "Profile", "Query", "compile"]


def compile(
    model: str | Path,
    *,
    profile: Profile | str = Profile.PRECOMPILED,
    queries: Sequence[str] | None = None,
    all: bool = False,
    givens: Mapping[str, Any] | None = None,
    data_root: str | Path | None = None,
    database: str | Path | None = None,
    title: str | None = None,
    timeout: float = 120,
    files: Mapping[str, str | Path] | None = None,
) -> Document:
    """Compile ordered notebook cells. Declare files used by SQL readers with files=."""
    import duckdb

    from pymalloy._errors import CompilationError, ModelError
    from pymalloy.export._compile import compile_document

    path = Path(model).resolve()
    root = Path(data_root).resolve() if data_root is not None else path.parent
    selected = query_names(queries, all=all)
    db = Path(database).resolve() if database is not None else None
    try:
        if files is not None and not isinstance(files, Mapping):
            raise TypeError("files must be a mapping of aliases to paths")
        return compile_document(
            path,
            queries=selected,
            all=all,
            givens=givens,
            data_root=root,
            database=db,
            timeout=timeout,
            profile=Profile(profile),
            title=title if title is not None else path.stem.replace("_", " ").title(),
            files={
                name: Path(value).resolve() for name, value in (files or {}).items()
            },
        )
    except (
        OSError,
        ValueError,
        TypeError,
        TimeoutError,
        ModelError,
        duckdb.Error,
    ) as error:
        raise CompilationError(str(error)) from error
