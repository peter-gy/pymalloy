"""Author, inspect, execute, and share Malloy models from Python.

Start with ``import pymalloy as pm``. Constructors build immutable syntax.
Malloy resolves language semantics, and runtime adapters execute with DuckDB.

Choose an entry point
--------------------
table, sql, data
    Start from a table/file, SQL source, or captured Python dataframe.
col, lit, given
    Reference a field, encode a scalar value, or reference a parameter.
draft, read_model
    Compose a new model or parse existing Malloy for scoped edits.
query, group_by, aggregate, select
    Build reusable query syntax. These constructors do not execute it.
connect
    Own native execution and compile models through Connection.model.
parse, format
    Inspect syntax or format Malloy source.
MalloyWidget
    Execute in a notebook browser and observe revision-bound results.

Notes
-----
The base package includes symbolic authoring, browser widgets, and agent guidance.
Native execution and compiler tooling require ``pymalloy[headless]``. Widgets
run without Deno. Install PyArrow directly for Python dataframe capture and
Polars directly for ``Result.to_polars()``. The headless extra already includes PyArrow.

Examples
--------
>>> import pymalloy as pm
>>> candidate = pm.draft().define(values=pm.sql("SELECT 42 AS amount"))
>>> candidate = candidate.queries(answer=pm.ref("values").pipe(
...     pm.query(pm.select(pm.col("amount")))
... ))
>>> pm.connect().model(candidate).query().run().to_pylist()
[{'amount': 42}]
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pymalloy._authoring.draft import Draft, draft, read_model
from pymalloy._model.source import ModelSource
from pymalloy.authoring import (
    Fragment,
    aggregate,
    data,
    dimension,
    group_by,
    having,
    join,
    limit,
    measure,
    nest,
    order_by,
    primary_key,
    query,
    ref,
    select,
    sql,
    syntax,
    table,
    view,
    where,
)
from pymalloy.errors import PyMalloyError
from pymalloy.expressions import (
    Expr,
    Sort,
    call,
    case,
    col,
    count,
    given,
    lit,
    number,
    raw_expr,
)
from pymalloy.result import Result

if TYPE_CHECKING:
    from pymalloy._headless.api import Connection, Model, Query, connect
    from pymalloy._headless.tooling import format, parse
    from pymalloy.widget import MalloyWidget

__all__ = [
    "Connection",
    "Draft",
    "Expr",
    "Fragment",
    "MalloyWidget",
    "Model",
    "ModelSource",
    "PyMalloyError",
    "Query",
    "Result",
    "Sort",
    "aggregate",
    "call",
    "case",
    "col",
    "connect",
    "count",
    "data",
    "dimension",
    "draft",
    "format",
    "given",
    "group_by",
    "having",
    "join",
    "limit",
    "lit",
    "measure",
    "nest",
    "number",
    "order_by",
    "parse",
    "primary_key",
    "query",
    "raw_expr",
    "read_model",
    "ref",
    "select",
    "sql",
    "syntax",
    "table",
    "view",
    "where",
]


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


def __getattr__(name: str):
    if name == "MalloyWidget":
        from pymalloy.widget import MalloyWidget

        return MalloyWidget
    if name in {"connect", "Connection", "Model", "Query"}:
        from pymalloy._headless import load_api

        return getattr(load_api(), name)
    if name in {"format", "parse"}:
        from pymalloy._headless import tooling

        return getattr(tooling, name)
    raise AttributeError(name)
