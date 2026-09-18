from __future__ import annotations

from typing import TYPE_CHECKING

from pymalloy._draft import Draft, draft, read_model
from pymalloy._errors import CompilationError, ModelError, SchemaError
from pymalloy._source import ModelSource
from pymalloy.analysis import QueryDescriptor
from pymalloy.authoring import (
    Fragment,
    aggregate,
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
    "Draft",
    "ExecutionContext",
    "ExecutionError",
    "Expr",
    "Fragment",
    "MalloyWidget",
    "Model",
    "ModelError",
    "ModelSource",
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
        from pymalloy.widget import MalloyWidget

        return MalloyWidget
    if name in {"model", "run", "check", "Model", "Query"}:
        from pymalloy._server import load_api

        return getattr(load_api(), name)
    if name in {"format", "parse"}:
        from pymalloy._server import tooling

        return getattr(tooling, name)
    raise AttributeError(name)
