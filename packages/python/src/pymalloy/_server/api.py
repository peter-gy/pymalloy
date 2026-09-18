from __future__ import annotations

import time
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any, TypedDict, Unpack

import duckdb

from pymalloy._draft import Draft
from pymalloy._source import ModelSource
from pymalloy.analysis import CheckReport, SourcePosition
from pymalloy.result import Result

from .runtime import Model, Query, _Runtime
from .validation import validate

__all__ = ["Model", "Query", "check", "model", "run", "validate"]


class _RuntimeOptions(TypedDict, total=False):
    data_root: str | Path | None
    database: str | Path | None
    connection: duckdb.DuckDBPyConnection | None
    tables: Mapping[str, Any] | None
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
    tables: Mapping[str, Any] | None = None,
    read_only: bool = False,
    timeout: float = 120,
    compiler_memory_mb: int = 256,
) -> Model:
    """Compile a reusable model that owns its compiler and data connection.

    Register Python data with `tables`. A supplied connection remains caller-owned.
    Models release resources when collected. Call `close()` to release them early.
    """
    deadline = time.monotonic() + timeout
    runtime = _Runtime(
        data_root=data_root,
        database=database,
        connection=connection,
        read_only=read_only,
        timeout=timeout,
        compiler_memory_mb=compiler_memory_mb,
        deadline=deadline,
    )
    try:
        return runtime.compile(source, url=url, tables=tables, deadline=deadline)
    except BaseException:
        runtime.close()
        raise


def run(
    source: str | Path | ModelSource | Draft,
    *,
    givens: Mapping[str, Any] | None = None,
    **options: Unpack[_ModelOptions],
) -> Result:
    """Execute a model's default query and release its resources before returning."""
    deadline = time.monotonic() + options.get("timeout", 120)
    with closing(model(source, **options)) as compiled:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Query execution exceeded its deadline")
        return compiled.run(givens=givens, timeout=remaining)


def check(
    source: str | Path | ModelSource | Draft,
    *,
    path: str | Path | None = None,
    url: str | None = None,
    tables: Mapping[str, Any] | None = None,
    syntax_only: bool = False,
    position: SourcePosition | None = None,
    data_root: str | Path | None = None,
    database: str | Path | None = None,
    connection: duckdb.DuckDBPyConnection | None = None,
    read_only: bool = False,
    timeout: float = 120,
    compiler_memory_mb: int = 256,
) -> CheckReport:
    """Check a draft and return diagnostics, schemas, and source metadata."""
    deadline = time.monotonic() + timeout
    with closing(
        _Runtime(
            data_root=data_root,
            database=database,
            connection=connection,
            read_only=read_only,
            timeout=timeout,
            compiler_memory_mb=compiler_memory_mb,
            deadline=deadline,
        )
    ) as runtime:
        return runtime.check(
            source,
            path=path,
            url=url,
            tables=tables,
            syntax_only=syntax_only,
            position=position,
            deadline=deadline,
        )
