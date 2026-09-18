from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pymalloy._document import Document, Markdown, Query

__all__ = ["Document", "Markdown", "Query", "compile_document"]


def compile_document(
    model: str | Path,
    *,
    profile: Literal["precompiled", "native", "widget"] = "precompiled",
    queries: Sequence[str] = (),
    givens: Mapping[str, Any] | None = None,
    data_root: str | Path | None = None,
    database: str | Path | None = None,
    title: str | None = None,
    timeout: float = 120,
) -> Document:
    """Prepare ordered notebook cells from a local model or document.

    `precompiled` emits fixed SQL. `native` hydrates a native model, and `widget`
    displays interactive browser queries. All profiles validate schemas at export.

    Models default to run statements, otherwise named queries or exported views.
    Documents preserve Markdown and executable cell order with default selection.
    Explicit `queries` produces query cells in selector order, using names,
    `source.view`, `run:N`, `sql:N`, or `*`. Data paths resolve against
    `data_root`, which defaults to the model directory. Existing databases open
    read-only. `givens` overrides declared defaults for this export.
    Raises `CompilationError` for input or compilation failures.
    """
    if profile not in {"precompiled", "native", "widget"}:
        raise ValueError("profile must be 'precompiled', 'native', or 'widget'")

    import duckdb
    from sqlglot.errors import SqlglotError

    from pymalloy.server._documents import compile_document as compile_native_document
    from pymalloy.server._errors import CompilationError, SessionError

    model = Path(model).resolve()
    root = Path(data_root).resolve() if data_root is not None else model.parent
    db = Path(database).resolve() if database is not None else None
    if not model.is_file():
        raise CompilationError(f"Model file does not exist: {model}")
    if db is not None and not db.is_file():
        raise CompilationError(f"Database file does not exist: {db}")
    if isinstance(queries, str):
        raise CompilationError(
            "Pass queries as a sequence, such as ['orders.by_region']"
        )
    if "*" in queries and len(queries) != 1:
        raise CompilationError("Use '*' by itself to select all queries")
    try:
        return compile_native_document(
            model,
            queries=queries,
            givens=givens,
            data_root=root,
            database=db,
            timeout=timeout,
            profile=profile,
            title=title if title is not None else model.stem.replace("_", " ").title(),
        )
    except (
        OSError,
        ValueError,
        TypeError,
        TimeoutError,
        SessionError,
        duckdb.Error,
        SqlglotError,
    ) as error:
        raise CompilationError(str(error)) from error
