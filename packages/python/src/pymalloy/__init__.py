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
model, run
    Retain a compiled model or execute once and release runtime resources.
parse, check, format
    Inspect syntax, check schemas/types, or format Malloy source.
MalloyWidget
    Execute in a notebook browser and observe revision-bound results.

Notes
-----
Syntax construction uses the lightweight base package. Native execution and
compiler tooling require ``pymalloy[server]``. Widgets need ``pymalloy[widget]``
and run without Deno. ``pymalloy[dataframes]`` adds Polars and Arrow, while
``pymalloy[agent]`` supplies installed agent guidance. Combine extras as needed.

Examples
--------
>>> import pymalloy as pm
>>> candidate = pm.draft().define(values=pm.sql("SELECT 42 AS amount"))
>>> candidate = candidate.queries(answer=pm.ref("values").pipe(
...     pm.query(pm.select(pm.col("amount")))
... ))
>>> pm.run(candidate).rows()
[{'amount': 42}]
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pymalloy._authoring.draft import Draft, draft, read_model
from pymalloy._model.errors import (
    CompilationError,
    CompilerError,
    ModelError,
    PyMalloyError,
    SchemaError,
)
from pymalloy._model.source import ModelSource
from pymalloy.analysis import QueryDescriptor
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
from pymalloy.execution import ExecutionContext, ExecutionError
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
    from pymalloy._server.api import Model, Query, check, model, run
    from pymalloy._server.tooling import format, parse
    from pymalloy.widget import MalloyWidget

__all__ = [
    "CompilationError",
    "CompilerError",
    "Draft",
    "ExecutionContext",
    "ExecutionError",
    "Expr",
    "Fragment",
    "MalloyWidget",
    "Model",
    "ModelError",
    "ModelSource",
    "PyMalloyError",
    "Query",
    "QueryDescriptor",
    "Result",
    "SchemaError",
    "Sort",
    "aggregate",
    "call",
    "case",
    "check",
    "col",
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
    "model",
    "nest",
    "number",
    "order_by",
    "parse",
    "primary_key",
    "query",
    "raw_expr",
    "read_model",
    "ref",
    "run",
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
        try:
            from pymalloy.widget import MalloyWidget
        except ModuleNotFoundError as error:
            if error.name in {"anywidget", "traitlets", "ipywidgets"}:
                raise ImportError("Browser widgets require pymalloy[widget]") from error
            raise
        return MalloyWidget
    if name in {"model", "run", "check", "Model", "Query"}:
        from pymalloy._server import load_api

        return getattr(load_api(), name)
    if name in {"format", "parse"}:
        from pymalloy._server import tooling

        return getattr(tooling, name)
    raise AttributeError(name)
