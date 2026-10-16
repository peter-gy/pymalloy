"""Author, inspect, execute, and share Malloy models from Python.

Start with ``import pymalloy as pm``. Constructors build immutable syntax.
Malloy resolves language semantics, and runtime adapters execute with DuckDB.

Choose an entry point
---------------------
table, sql, data
    Start from a table/file, SQL source, or captured Python dataframe.
col, lit, given
    Reference a field, encode a scalar value, or reference a parameter.
draft, read_model
    Compose a new model or parse existing Malloy for scoped edits.
source, view
    Reference a relation and build reusable query stages with method chains.
connect
    Own native execution and compile models through Connection.model.
parse, format
    Inspect syntax or format Malloy source.
MalloyWidget
    Execute in a notebook browser and observe revision-bound results.

Notes
-----
Native wheels include authoring, compiler tooling, DuckDB execution, browser
widgets, and agent guidance. PyArrow supplies dataframe capture and columnar
results. Install Polars separately for ``Result.to_polars()``.

Examples
--------
>>> import pymalloy as pm
>>> model = (
...     pm.draft()
...     .sources(values=pm.sql("SELECT 42 AS amount"))
...     .queries(answer=pm.source("values").pipe(pm.view().select("amount")))
... )
>>> with pm.connect() as con:
...     con.model(model).query("answer").run().to_pylist()
[{'amount': 42}]
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pymalloy._authoring.draft import Draft, draft, read_model
from pymalloy._model.source import ModelSource
from pymalloy.authoring import Source, View, data, source, sql, table, view
from pymalloy.errors import PyMalloyError
from pymalloy.expressions import Expr, Sort, case, col, count, given, lit
from pymalloy.result import Result

if TYPE_CHECKING:
    from pymalloy._compiler.tooling import format, parse
    from pymalloy._runtime.connection import Connection, Model, Query, connect
    from pymalloy.widget import MalloyWidget

__all__ = [
    "Connection",
    "Draft",
    "Expr",
    "MalloyWidget",
    "Model",
    "ModelSource",
    "PyMalloyError",
    "Query",
    "Result",
    "Sort",
    "Source",
    "View",
    "case",
    "col",
    "connect",
    "count",
    "data",
    "draft",
    "format",
    "given",
    "lit",
    "parse",
    "read_model",
    "source",
    "sql",
    "table",
    "view",
]


def __dir__() -> list[str]:
    return __all__


def __getattr__(name: str):
    if name == "MalloyWidget":
        from pymalloy.widget import MalloyWidget

        return MalloyWidget
    if name in {"connect", "Connection", "Model", "Query"}:
        from pymalloy._runtime import connection

        return getattr(connection, name)
    if name in {"format", "parse"}:
        from pymalloy._compiler import tooling

        return getattr(tooling, name)
    raise AttributeError(name)
