"""Compose Malloy model syntax from symbolic scalar expressions and query clauses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pymalloy._identifiers import identifier
from pymalloy._syntax import (
    Fragment,
    binding,
    block,
    named_clause,
    syntax,
)
from pymalloy._syntax import (
    scalar_expression as _scalar,
)
from pymalloy.expressions import Expr, Sort

__all__ = [
    "Fragment",
    "aggregate",
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


def table(path: str | Path) -> Fragment:
    value = (
        "'" + path.as_posix().replace("'", "''") + "'"
        if isinstance(path, Path)
        else path
    )
    return syntax(f"duckdb.table({json.dumps(value, ensure_ascii=False)})")


def sql(text: str) -> Fragment:
    return syntax(f"duckdb.sql({json.dumps(text, ensure_ascii=False)})")


def ref(name: str) -> Fragment:
    return syntax(identifier(name))


def dimension(**fields: Expr) -> Fragment:
    return named_clause("dimension", fields)


def measure(**fields: Expr) -> Fragment:
    return named_clause("measure", fields)


def view(**queries: Fragment) -> Fragment:
    return named_clause("view", queries, kind="query")


def query(*clauses: Fragment) -> Fragment:
    return block(clauses)


def _fields(keyword: str, fields: tuple[Expr, ...], named: dict[str, Expr]) -> Fragment:
    values: list[Fragment | Expr] = [_scalar(field) for field in fields]
    values.extend(binding("field", name, value) for name, value in named.items())
    if not values:
        raise ValueError(f"{keyword} requires fields")
    parts: list[str | Fragment | Expr] = [keyword + ": "]
    for index, value in enumerate(values):
        if index:
            parts.append(", ")
        parts.append(value)
    return syntax(*parts)


def group_by(*fields: Expr, **named: Expr) -> Fragment:
    return _fields("group_by", fields, named)


def aggregate(*fields: Expr, **named: Expr) -> Fragment:
    return _fields("aggregate", fields, named)


def select(*fields: Expr, **named: Expr) -> Fragment:
    return _fields("select", fields, named)


def nest(**queries: Fragment) -> Fragment:
    return named_clause("nest", queries, kind="query")


def where(predicate: Expr) -> Fragment:
    return syntax("where: ", _scalar(predicate))


def having(predicate: Expr) -> Fragment:
    return syntax("having: ", _scalar(predicate))


def order_by(*fields: Expr | Sort) -> Fragment:
    if not fields:
        raise ValueError("order_by requires fields")
    parts: list[str | Fragment | Expr] = ["order_by: "]
    for index, field in enumerate(fields):
        if index:
            parts.append(", ")
        if isinstance(field, Sort):
            parts.extend(
                (_scalar(field.expression), " desc" if field.descending else " asc")
            )
        else:
            parts.append(_scalar(field))
    return syntax(*parts)


def limit(rows: int) -> Fragment:
    if type(rows) is not int or rows < 0:
        raise ValueError("Limit must be a nonnegative integer")
    return syntax(f"limit: {rows}")


def primary_key(field: str) -> Fragment:
    return syntax("primary_key: ", identifier(field))


def join(
    name: str, source: Fragment, *, on: Expr, kind: Literal["one", "many", "cross"]
) -> Fragment:
    if kind not in {"one", "many", "cross"}:
        raise ValueError("Join kind must be one, many, or cross")
    value = binding("source", name, source)
    # The condition is syntax owned by the join, not a second named RHS slot.
    value = syntax(
        *value.parts,
        " on ",
        syntax(_scalar(on), kind="clause"),
        kind="source",
        name=name,
    )
    return syntax(f"join_{kind}: ", value)
