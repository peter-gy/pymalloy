from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any, TypedDict, Unpack

import duckdb

from pymalloy._authoring.draft import Draft
from pymalloy._model import DEFAULT_CONNECTION
from pymalloy._model.source import DocumentKind, ModelSource
from pymalloy.analysis import CheckReport, SourcePosition
from pymalloy.result import Result

from .runtime import Model, Query, _Runtime
from .tooling import compiler_lease
from .validation import validate

__all__ = ["Model", "Query", "check", "model", "run", "validate"]


class _RuntimeOptions(TypedDict, total=False):
    data_root: str | Path | None
    database: str | Path | None
    connection: duckdb.DuckDBPyConnection | None
    config: Mapping[str, Any] | None
    extensions: Sequence[str]
    connection_name: str
    document_kind: DocumentKind | None
    read_only: bool
    timeout: float
    compiler_memory_mb: int


class _ModelOptions(_RuntimeOptions, total=False):
    url: str | None


def model(
    source: str | Path | ModelSource | Draft,
    *,
    url: str | None = None,
    data_root: str | Path | None = None,
    database: str | Path | None = None,
    connection: duckdb.DuckDBPyConnection | None = None,
    config: Mapping[str, Any] | None = None,
    extensions: Sequence[str] = (),
    connection_name: str = DEFAULT_CONNECTION,
    document_kind: DocumentKind | None = None,
    read_only: bool = False,
    timeout: float = 120,
    compiler_memory_mb: int = 256,
) -> Model:
    """Compile source into a reusable model backed by native DuckDB.

    Use a retained model when preparing several queries or varying parameters.
    Use run for one execution whose resources can be released immediately.
    Requires ``pymalloy[server]``.

    Parameters
    ----------
    source : str, pathlib.Path, ModelSource, or Draft
        Malloy text, file Path, closed source snapshot, or authored draft. A
        string is text, not a filename. Use Path("orders.malloy") for a file.
    url : str, optional
        Absolute identity/base URL for inline text. File paths and snapshots
        carry their own identity. Defaults to data_root/model.malloy when data_root is supplied, otherwise
        model.malloy in the working directory.
    data_root : str or pathlib.Path, optional
        Search directory for relative data files on an owned connection. Source
        identity separately controls imports. DuckDB checks the working directory
        first. Rejected with a borrowed connection, which retains its existing settings.
    database : str or pathlib.Path, optional
        DuckDB database file. Omitted means a new in-memory database. Mutually
        exclusive with connection.
    connection : duckdb.DuckDBPyConnection, optional
        Borrow the caller's connection. It is never closed by the model, and
        its settings and transactions remain caller-owned.
    config : mapping, optional
        Native DuckDB settings for an owned connection, such as threads or
        memory_limit. Rejected with a borrowed connection. An explicit
        file_search_path conflicts with data_root.
    extensions : sequence of str, default ()
        DuckDB extensions to install/load before file-access restrictions are
        applied. Installation may need network access. Nonempty values are
        rejected for borrowed connections.
    connection_name : str, default "duckdb"
        Malloy connection identifier. This names the DuckDB adapter, not a
        choice of database engine. Match connection= in table/sql/data constructors.
    document_kind : {"model", "notebook"}, optional
        Override extension-based classification. Notebook includes .malloynb
        and .malloysql documents. Plain inline text defaults to model syntax.
    read_only : bool, default False
        Open the owned database read-only. True is rejected with a borrowed connection.
    timeout : float, default 120
        Positive finite seconds for startup/compilation and the default budget
        for later operations. Each operation includes waiting, compilation and SQL.
    compiler_memory_mb : int, default 256
        V8 compiler heap budget in MiB, separate from DuckDB's memory_limit.

    Returns
    -------
    Model
        Reusable query inventory and runtime. Call close for prompt release.
        Queries keep their model alive. Materialized results survive closure.

    Raises
    ------
    CompilationError
        Malloy source or schema resolution fails, with compiler diagnostics.
    CompilerError
        The compiler process or protocol fails.
    TimeoutError
        The operation's shared deadline expires.

    Notes
    -----
    A SQL timeout interrupts that statement and leaves a healthy model reusable.
    A timeout during an in-flight compiler request makes that model terminal.
    An interrupted caller-owned transaction may require a caller rollback.

    Examples
    --------
    >>> import pymalloy as pm
    >>> from pathlib import Path
    >>> model = pm.model("run: duckdb.sql('SELECT 42 AS answer') -> {select: answer}")
    >>> model.query().run().rows()
    [{'answer': 42}]
    >>> model.close()
    >>> model.closed
    True
    """
    deadline = time.monotonic() + timeout
    runtime = _Runtime(
        data_root=data_root,
        database=database,
        connection=connection,
        config=config,
        extensions=extensions,
        connection_name=connection_name,
        read_only=read_only,
        timeout=timeout,
        compiler_memory_mb=compiler_memory_mb,
        deadline=deadline,
    )
    try:
        return runtime.compile(
            source, url=url, document_kind=document_kind, deadline=deadline
        )
    except BaseException:
        runtime.close()
        raise


def run(
    source: str | Path | ModelSource | Draft,
    *,
    givens: Mapping[str, Any] | None = None,
    **options: Unpack[_ModelOptions],
) -> Result:
    """Execute a default query once and return materialized results.

    Parameters
    ----------
    source : str, pathlib.Path, ModelSource, or Draft
        Source accepted by model. A string is Malloy text. Use Path for files.
    givens : mapping, optional
        Values for declared Malloy parameters. Values are bound for this call.
    **options
        Options accepted by model, including data_root, database, connection,
        connection_name, config and timeout. One deadline covers compilation
        and execution. A supplied connection remains caller-owned.

    Returns
    -------
    Result
        SQL, columns and Arrow-backed values. Owned runtime resources are closed
        before return. Use .rows(), .arrow(), or .polars() to read the data.

    Notes
    -----
    Selects the last authored run, or the sole available query when there are no
    runs. Multiple named queries/views require ``model(...).query(name).run()``.

    Examples
    --------
    >>> import pymalloy as pm
    >>> result = pm.run("run: duckdb.sql('SELECT 42 AS answer') -> {select: answer}")
    >>> result.rows()
    [{'answer': 42}]
    """
    deadline = time.monotonic() + options.get("timeout", 120)
    with model(source, **options) as compiled:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Query execution exceeded its deadline")
        return compiled.run(givens=givens, timeout=remaining)


def check(
    source: str | Path | ModelSource | Draft,
    *,
    path: str | Path | None = None,
    url: str | None = None,
    connection_name: str = DEFAULT_CONNECTION,
    document_kind: DocumentKind | None = None,
    syntax_only: bool = False,
    position: SourcePosition | None = None,
    data_root: str | Path | None = None,
    database: str | Path | None = None,
    connection: duckdb.DuckDBPyConnection | None = None,
    config: Mapping[str, Any] | None = None,
    extensions: Sequence[str] = (),
    read_only: bool = False,
    timeout: float = 120,
    compiler_memory_mb: int = 256,
) -> CheckReport:
    """Return compiler diagnostics and model metadata without executing result queries.

    Parameters
    ----------
    source : str, pathlib.Path, ModelSource, or Draft
        Source to check. Strings contain Malloy text, Paths name files.
    path : str or pathlib.Path, optional
        Identity hint for inline text, used for locations and relative imports.
    url : str, optional
        Absolute identity hint. Mutually exclusive with path.
    connection_name : str, default "duckdb"
        Malloy name for the native DuckDB adapter.
    document_kind : {"model", "notebook"}, optional
        Explicit parser mode, otherwise inferred from source identity.
    syntax_only : bool, default False
        Stop after syntax/tooling analysis. No table schema discovery or imported
        model resolution is performed. Runtime dependencies are still required.
    position : SourcePosition, optional
        Zero-based line and Unicode code-point character position for contextual
        completion and help metadata. Import from pymalloy.analysis.
    data_root : str or pathlib.Path, optional
        Search directory for data files on the owned connection.
    database : str or pathlib.Path, optional
        DuckDB database file, mutually exclusive with connection.
    connection : duckdb.DuckDBPyConnection, optional
        Caller-owned connection for schema discovery. It remains open.
    config : mapping, optional
        Native settings for an owned connection, as in model.
    extensions : sequence of str, default ()
        Extensions to install/load on an owned connection before restrictions.
    read_only : bool, default False
        Open an owned database read-only.
    timeout : float, default 120
        Positive finite deadline in seconds, including compiler acquisition,
        startup and schema discovery.
    compiler_memory_mb : int, default 256
        Compiler V8 heap budget in MiB.

    Returns
    -------
    CheckReport
        ok, diagnostics, model/schema metadata, query inventory and tooling data.
        Infrastructure failures raise exceptions instead of becoming diagnostics.

    See Also
    --------
    Draft.check : Add opt-in documentation lint.
    Draft.validate : Execute data assertions.
    parse : Syntax-only tooling without a DuckDB connection.

    Examples
    --------
    >>> import pymalloy as pm
    >>> report = pm.check("run: missing_source")
    >>> report.ok
    False
    >>> report.diagnostics[0].code
    'source-or-query-not-found'
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Operation timeout must be finite and positive")
    deadline = time.monotonic() + timeout
    with (
        compiler_lease(deadline, memory_mb=compiler_memory_mb) as compiler,
        closing(
            _Runtime(
                data_root=data_root,
                database=database,
                connection=connection,
                config=config,
                extensions=extensions,
                connection_name=connection_name,
                read_only=read_only,
                timeout=timeout,
                compiler_memory_mb=compiler_memory_mb,
                deadline=deadline,
                compiler=compiler,
            )
        ) as runtime,
    ):
        return runtime.check(
            source,
            path=path,
            url=url,
            syntax_only=syntax_only,
            position=position,
            document_kind=document_kind,
            deadline=deadline,
        )
