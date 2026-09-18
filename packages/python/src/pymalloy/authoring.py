"""Compose Malloy model syntax from symbolic scalar expressions and query clauses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pymalloy._connection import DEFAULT_CONNECTION
from pymalloy._identifiers import identifier
from pymalloy._inputs import snapshot_data
from pymalloy._records import SyntaxOperationKind
from pymalloy._syntax import (
    Fragment,
    binding,
    block,
    construct,
    named_clause,
    syntax,
)
from pymalloy._syntax import (
    scalar_expression as _scalar,
)
from pymalloy._table import TableReference, table_path
from pymalloy.expressions import Expr, Sort

__all__ = [
    "Fragment",
    "aggregate",
    "data",
    "dimension",
    "group_by",
    "having",
    "join",
    "limit",
    "measure",
    "nest",
    "order_by",
    "primary_key",
    "query",
    "ref",
    "select",
    "sql",
    "syntax",
    "table",
    "view",
    "where",
]


def table(path: str | Path, *, connection: str = DEFAULT_CONNECTION) -> Fragment:
    return syntax(TableReference(connection, table_path(path)))


def data(
    frame: Any, *, name: str | None = None, connection: str = DEFAULT_CONNECTION
) -> Fragment:
    """Capture dataframe-like input as an immutable, composable Malloy source."""
    captured = snapshot_data(frame, name=name)
    return syntax(TableReference(connection, captured.reference, data=captured))


def sql(text: str, *, connection: str = DEFAULT_CONNECTION) -> Fragment:
    return construct(
        "sql",
        f"{identifier(connection)}.sql({json.dumps(text, ensure_ascii=False)})",
        arguments=(text, connection),
    )


def ref(name: str) -> Fragment:
    return construct("ref", identifier(name), arguments=(name,))


def dimension(**fields: Expr) -> Fragment:
    return named_clause("dimension", fields)


def measure(**fields: Expr) -> Fragment:
    return named_clause("measure", fields)


def view(**queries: Fragment) -> Fragment:
    return named_clause("view", queries, kind="query")


def query(*clauses: Fragment) -> Fragment:
    return block(clauses)


def _fields(
    keyword: SyntaxOperationKind, fields: tuple[Expr, ...], named: dict[str, Expr]
) -> Fragment:
    values: list[Fragment | Expr] = [_scalar(field) for field in fields]
    values.extend(binding("field", name, value) for name, value in named.items())
    if not values:
        raise ValueError(f"{keyword} requires fields")
    parts: list[str | Fragment | Expr] = [keyword + ": "]
    for index, value in enumerate(values):
        if index:
            parts.append(", ")
        parts.append(value)
    return construct(keyword, *parts)


def group_by(*fields: Expr, **named: Expr) -> Fragment:
    return _fields("group_by", fields, named)


def aggregate(*fields: Expr, **named: Expr) -> Fragment:
    return _fields("aggregate", fields, named)


def select(*fields: Expr, **named: Expr) -> Fragment:
    return _fields("select", fields, named)


def nest(**queries: Fragment) -> Fragment:
    return named_clause("nest", queries, kind="query")


def where(predicate: Expr) -> Fragment:
    return construct("where", "where: ", _scalar(predicate))


def having(predicate: Expr) -> Fragment:
    return construct("having", "having: ", _scalar(predicate))


def order_by(*fields: Expr | Sort) -> Fragment:
    if not fields:
        raise ValueError("order_by requires fields")
    parts: list[str | Fragment | Expr] = ["order_by: "]
    for index, field in enumerate(fields):
        if index:
            parts.append(", ")
        if isinstance(field, Sort):
            direction = "desc" if field.descending else "asc"
            parts.append(
                construct(direction, _scalar(field.expression), " " + direction)
            )
        else:
            parts.append(_scalar(field))
    return construct("order_by", *parts)


def limit(rows: int) -> Fragment:
    if type(rows) is not int or rows < 0:
        raise ValueError("Limit must be a nonnegative integer")
    return construct("limit", f"limit: {rows}", arguments=(str(rows),))


def primary_key(field: str) -> Fragment:
    return construct(
        "primary_key", "primary_key: ", identifier(field), arguments=(field,)
    )


def join(
    name: str, source: Fragment, *, on: Expr, kind: Literal["one", "many", "cross"]
) -> Fragment:
    if kind not in {"one", "many", "cross"}:
        raise ValueError("Join kind must be one, many, or cross")
    value = binding("source", name, source)
    # The condition is syntax owned by the join, not a second named RHS slot.
    value = Fragment(
        (*value.parts, " on ", syntax(_scalar(on), kind="clause")),
        kind="source",
        name=name,
        _layout=True,
    )
    return Fragment((f"join_{kind}: ", value), _layout=True)
