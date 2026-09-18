"""Immutable scalar expressions compiled with Malloy's own language semantics."""

from __future__ import annotations

import builtins
import datetime
import decimal
import math
import re
from dataclasses import dataclass
from functools import cached_property
from typing import NoReturn

from pymalloy._expression_ops import render
from pymalloy._identifiers import identifier
from pymalloy._records import (
    Branch,
    Scalar,
    ScalarBinary,
    ScalarCall,
    ScalarCase,
    ScalarCast,
    ScalarField,
    ScalarFilter,
    ScalarGiven,
    ScalarLiteral,
    ScalarNullTest,
    ScalarRaw,
    ScalarTruncate,
    ScalarUnary,
)

__all__ = [
    "Expr",
    "Sort",
    "call",
    "case",
    "col",
    "count",
    "given",
    "lit",
    "number",
    "raw_expr",
]

type Literal = (
    str
    | int
    | float
    | decimal.Decimal
    | bool
    | datetime.date
    | datetime.datetime
    | None
)
type IntoExpr = Expr | Literal


@dataclass(frozen=True, eq=False, init=False)
class Expr:
    """A symbolic scalar value. Names, types, and aggregate scope resolve in Malloy."""

    _node: Scalar
    _source: builtins.str | None
    _documentation: builtins.str | None
    __hash__ = None

    def __init__(self) -> None:
        raise TypeError("Create expressions with col(), lit(), or raw_expr()")

    @classmethod
    def _from_node(
        cls,
        node: Scalar,
        *,
        source: builtins.str | None = None,
        documentation: builtins.str | None = None,
    ) -> Expr:
        result = object.__new__(cls)
        object.__setattr__(result, "_node", node)
        object.__setattr__(result, "_source", source)
        object.__setattr__(result, "_documentation", documentation)
        return result

    def _with_node(self, node: Scalar) -> Expr:
        return self._from_node(node, documentation=self._documentation)

    def doc(self, text: builtins.str) -> Expr:
        """Attach documentation for a named field while retaining scalar operations."""
        if not isinstance(text, builtins.str) or not text.strip():
            raise ValueError("Documentation must be nonempty text")
        return self._from_node(self._node, source=self._source, documentation=text)

    @cached_property
    def text(self) -> builtins.str:
        return self._source if self._source is not None else render(self._node)

    def __repr__(self) -> builtins.str:
        return f"Expr({self.text!r})"

    def equals(self, other: Expr) -> bool:
        """Compare operation trees without constructing a query predicate."""
        return isinstance(other, Expr) and self._node == other._node

    def __bool__(self) -> NoReturn:
        raise TypeError(
            "An Expr has no Python truth value. Use &, |, and ~ for predicates."
        )

    def __iter__(self) -> NoReturn:
        raise TypeError("An Expr is a scalar expression, not a Python iterable.")

    def _binary(
        self, operator: builtins.str, other: IntoExpr, *, reverse: bool = False
    ) -> Expr:
        left, right = self._node, _expr(other)._node
        if reverse:
            left, right = right, left
        return self._with_node(ScalarBinary(operator=operator, left=left, right=right))

    def _call(self, name: builtins.str, *args: IntoExpr) -> Expr:
        return self._with_node(call(name, self, *args)._node)

    def __add__(self, other: IntoExpr) -> Expr:
        return self._binary("+", other)

    def __radd__(self, other: IntoExpr) -> Expr:
        return self._binary("+", other, reverse=True)

    def __sub__(self, other: IntoExpr) -> Expr:
        return self._binary("-", other)

    def __rsub__(self, other: IntoExpr) -> Expr:
        return self._binary("-", other, reverse=True)

    def __mul__(self, other: IntoExpr) -> Expr:
        return self._binary("*", other)

    def __rmul__(self, other: IntoExpr) -> Expr:
        return self._binary("*", other, reverse=True)

    def __truediv__(self, other: IntoExpr) -> Expr:
        return self._binary("/", other)

    def __rtruediv__(self, other: IntoExpr) -> Expr:
        return self._binary("/", other, reverse=True)

    def __mod__(self, other: IntoExpr) -> Expr:
        return self._binary("%", other)

    def __rmod__(self, other: IntoExpr) -> Expr:
        return self._binary("%", other, reverse=True)

    def __pow__(self, other: IntoExpr) -> Expr:
        return self._call("pow", other)

    def __rpow__(self, other: IntoExpr) -> Expr:
        return self._with_node(call("pow", other, self)._node)

    def __neg__(self) -> Expr:
        return self._with_node(ScalarUnary(operator="-", value=self._node))

    def __eq__(self, other: IntoExpr) -> Expr:  # ty: ignore[invalid-method-override]
        return self._binary("=", other)

    def __ne__(self, other: IntoExpr) -> Expr:  # ty: ignore[invalid-method-override]
        return self._binary("!=", other)

    def __lt__(self, other: IntoExpr) -> Expr:
        return self._binary("<", other)

    def __le__(self, other: IntoExpr) -> Expr:
        return self._binary("<=", other)

    def __gt__(self, other: IntoExpr) -> Expr:
        return self._binary(">", other)

    def __ge__(self, other: IntoExpr) -> Expr:
        return self._binary(">=", other)

    def __and__(self, other: IntoExpr) -> Expr:
        return self._binary("and", other)

    def __rand__(self, other: IntoExpr) -> Expr:
        return self._binary("and", other, reverse=True)

    def __or__(self, other: IntoExpr) -> Expr:
        return self._binary("or", other)

    def __ror__(self, other: IntoExpr) -> Expr:
        return self._binary("or", other, reverse=True)

    def __invert__(self) -> Expr:
        return self._with_node(ScalarUnary(operator="not", value=self._node))

    def is_null(self) -> Expr:
        return self._with_node(ScalarNullTest(value=self._node, negated=False))

    def is_not_null(self) -> Expr:
        return self._with_node(ScalarNullTest(value=self._node, negated=True))

    def fill_null(self, value: IntoExpr) -> Expr:
        return self._binary("??", value)

    def nullif(self, value: IntoExpr) -> Expr:
        return self._call("nullif", value)

    def _aggregate(self, name: builtins.str) -> Expr:
        if isinstance(self._node, ScalarField):
            return self._with_node(call(name, receiver=tuple(self._node.path))._node)
        return self._call(name)

    def sum(self) -> Expr:
        return self._aggregate("sum")

    def avg(self) -> Expr:
        return self._aggregate("avg")

    def min(self) -> Expr:
        return self._aggregate("min")

    def max(self) -> Expr:
        return self._aggregate("max")

    def count_distinct(self) -> Expr:
        """Count distinct nonnull values with Malloy's count(expression)."""
        return self._call("count")

    def cast(self, type: builtins.str, *, safe: bool = False) -> Expr:
        if not isinstance(type, str) or not type.strip():
            raise ValueError("Cast type must contain a Malloy or native SQL type")
        return self._with_node(ScalarCast(value=self._node, type=type, safe=safe))

    def filter(self, predicate: Expr) -> Expr:
        """Filter the input of an aggregate expression."""
        if not isinstance(predicate, Expr):
            raise TypeError("An aggregate filter requires an Expr predicate")
        return self._with_node(
            ScalarFilter(value=self._node, predicate=predicate._node)
        )

    def asc(self) -> Sort:
        return Sort(self, descending=False)

    def desc(self) -> Sort:
        return Sort(self, descending=True)

    @property
    def str(self) -> StringExpr:
        return StringExpr(self)

    @property
    def dt(self) -> DateTimeExpr:
        return DateTimeExpr(self)


@dataclass(frozen=True, eq=False)
class Sort:
    expression: Expr
    descending: bool = False

    @property
    def text(self) -> builtins.str:
        return self.expression.text + (" desc" if self.descending else " asc")


def _expr(value: IntoExpr) -> Expr:
    return value if isinstance(value, Expr) else lit(value)


def col(*path: str) -> Expr:
    if not path:
        raise ValueError("A column requires at least one path component")
    for name in path:
        identifier(name)
    return Expr._from_node(ScalarField(path=path))


def given(name: str) -> Expr:
    if not isinstance(name, str) or not name.isidentifier():
        raise ValueError("A given requires an identifier name")
    return Expr._from_node(ScalarGiven(name=name))


def lit(value: Literal) -> Expr:
    if value is None:
        node = ScalarLiteral(type="null", value="null")
    elif isinstance(value, bool):
        node = ScalarLiteral(type="boolean", value="true" if value else "false")
    elif isinstance(value, str):
        node = ScalarLiteral(type="string", value=value)
    elif isinstance(value, datetime.datetime):
        node = ScalarLiteral(type="timestamp", value=value.isoformat())
    elif isinstance(value, datetime.date):
        node = ScalarLiteral(type="date", value=value.isoformat())
    elif isinstance(value, int) or (
        isinstance(value, decimal.Decimal) and value.is_finite()
    ):
        node = ScalarLiteral(type="number", value=str(value))
    elif isinstance(value, float) and math.isfinite(value):
        node = ScalarLiteral(type="number", value=repr(value))
    else:
        raise TypeError(
            "Use a string, integer, finite float or Decimal, boolean, date, datetime, or None as a literal"
        )
    return Expr._from_node(node)


_NUMBER = re.compile(r"-?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def number(text: str) -> Expr:
    """Preserve a finite numeric literal's exact spelling and compiler-inferred type."""
    if not isinstance(text, str) or _NUMBER.fullmatch(text) is None:
        raise ValueError("A number requires one finite Malloy numeric literal")
    try:
        finite = decimal.Decimal(text).is_finite()
    except decimal.InvalidOperation:
        finite = False
    if not finite:
        raise ValueError("A number requires one finite Malloy numeric literal")
    return Expr._from_node(ScalarLiteral(type="number", value=text))


def raw_expr(code: str) -> Expr:
    """Use explicit Malloy syntax for an expression outside the symbolic grammar."""
    if not isinstance(code, str) or not code.strip():
        raise ValueError("A raw expression requires Malloy text")
    return Expr._from_node(ScalarRaw(code=code))


def call(name: str, *args: IntoExpr, receiver: tuple[str, ...] | None = None) -> Expr:
    identifier(name)
    if receiver is not None:
        if not isinstance(receiver, tuple) or not receiver:
            raise ValueError(
                "A call receiver requires a nonempty tuple of path components"
            )
        for part in receiver:
            identifier(part)
    return Expr._from_node(
        ScalarCall(
            name=name, args=tuple(_expr(arg)._node for arg in args), receiver=receiver
        )
    )


def count(*scope: str) -> Expr:
    """Count source rows, optionally relative to a joined source path."""
    return call("count", receiver=scope or None)


def case(*branches: tuple[Expr, IntoExpr], otherwise: IntoExpr) -> Expr:
    if not branches:
        raise ValueError("A case requires at least one condition and result pair")
    values = []
    for condition, value in branches:
        if not isinstance(condition, Expr):
            raise TypeError("A case condition must be an Expr")
        values.append(Branch(when=condition._node, then=_expr(value)._node))
    return Expr._from_node(
        ScalarCase(branches=tuple(values), otherwise=_expr(otherwise)._node)
    )


@dataclass(frozen=True, eq=False)
class StringExpr:
    expression: Expr

    def lower(self) -> Expr:
        return self.expression._call("lower")

    def upper(self) -> Expr:
        return self.expression._call("upper")

    def length(self) -> Expr:
        return self.expression._call("length")

    def contains(self, value: IntoExpr) -> Expr:
        """Match a literal substring. Use raw_expr for regular-expression syntax."""
        return self.expression._call("strpos", value) > 0

    def starts_with(self, value: IntoExpr) -> Expr:
        return self.expression._call("starts_with", value)

    def ends_with(self, value: IntoExpr) -> Expr:
        return self.expression._call("ends_with", value)

    def strip(self) -> Expr:
        return self.expression._call("trim")

    def replace(self, old: IntoExpr, new: IntoExpr) -> Expr:
        return self.expression._call("replace", old, new)


_TIME_UNITS = frozenset(
    {"year", "quarter", "month", "week", "day", "hour", "minute", "second"}
)


@dataclass(frozen=True, eq=False)
class DateTimeExpr:
    expression: Expr

    def year(self) -> Expr:
        return self.expression._call("year")

    def month(self) -> Expr:
        return self.expression._call("month")

    def day(self) -> Expr:
        return self.expression._call("day")

    def hour(self) -> Expr:
        return self.expression._call("hour")

    def minute(self) -> Expr:
        return self.expression._call("minute")

    def second(self) -> Expr:
        return self.expression._call("second")

    def truncate(self, unit: str) -> Expr:
        if unit not in _TIME_UNITS:
            raise ValueError(
                "Choose year, quarter, month, week, day, hour, minute, or second"
            )
        return self.expression._with_node(
            ScalarTruncate(value=self.expression._node, unit=unit)
        )

    def date(self) -> Expr:
        return self.expression.cast("date")
