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

from pymalloy._authoring.annotations import with_annotation
from pymalloy._authoring.identifiers import identifier
from pymalloy._authoring.operations import render
from pymalloy._notebook import NotebookDisplay
from pymalloy._protocol.records import (
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
class Expr(NotebookDisplay):
    """Build an immutable scalar expression for Malloy to resolve.

    Create expressions with col, lit, given, or raw_expr. Arithmetic, comparisons,
    and aggregate methods build syntax, not Python values. Use ``&``, ``|``, and
    ``~`` for boolean expressions and parentheses around comparisons. Python
    ``and``, ``or``, ``not``, truth testing, and iteration are unsupported.

    Attributes
    ----------
    text : str
        Malloy scalar syntax. Rendering does not execute the expression.
    str : StringExpr
        String operations, for example ``col("name").str.lower()``.
    dt : DateTimeExpr
        Temporal extraction, truncation, and date conversion.

    See Also
    --------
    col, lit, given, measure, dimension

    Examples
    --------
    >>> import pymalloy as pm
    >>> revenue = pm.col("amount").sum()
    >>> revenue.text
    'amount.sum()'
    >>> positive = (pm.col("amount") > 0) & pm.col("region").is_not_null()
    >>> revenue.equals(pm.col("amount").sum())
    True
    """

    _node: Scalar
    _source: builtins.str | None
    _annotations: tuple[tuple[builtins.str, builtins.str], ...]

    def __init__(self) -> None:
        raise TypeError("Create expressions with col(), lit(), or raw_expr()")

    @classmethod
    def _from_node(
        cls,
        node: Scalar,
        *,
        source: builtins.str | None = None,
        annotations: tuple[tuple[builtins.str, builtins.str], ...] = (),
    ) -> Expr:
        result = object.__new__(cls)
        object.__setattr__(result, "_node", node)
        object.__setattr__(result, "_source", source)
        object.__setattr__(result, "_annotations", annotations)
        return result

    def _with_node(self, node: Scalar) -> Expr:
        return self._from_node(node, annotations=self._annotations)

    def annotate(self, text: builtins.str, *, route: builtins.str = "") -> Expr:
        """Attach or replace one native annotation route.

        Parameters
        ----------
        text : str
            Nonempty annotation content. It is retained until the expression is
            bound as a named field, for example by measure or dimension.
        route : str, default ""
            Empty for renderer tags, '"' for documentation, or an application route
            such as "research". Other routes remain unchanged.

        Returns
        -------
        Expr
            A new expression with the same operations and updated annotations.

        Examples
        --------
        >>> import pymalloy as pm
        >>> amount = pm.col("amount").sum().annotate("unit=USD", route="research")
        >>> source = pm.sql("SELECT 1 AS amount").extend(pm.measure(revenue=amount))
        >>> "unit=USD" in source.text
        True
        """
        return self._from_node(
            self._node,
            source=self._source,
            annotations=with_annotation(self._annotations, text, route),
        )

    def doc(self, text: builtins.str) -> Expr:
        """Document the meaning of a named field or measure.

        Parameters
        ----------
        text : str
            Nonempty documentation, ideally stating units or the aggregation unit.
            Replaces this expression's documentation route and preserves other routes.

        Returns
        -------
        Expr
            A composable expression. Its description is emitted when it is named.

        Examples
        --------
        >>> import pymalloy as pm
        >>> revenue = pm.col("amount").sum().doc("Gross booked amount in USD.")
        >>> revenue.equals(pm.col("amount").sum())
        True
        """
        return self.annotate(text, route='"')

    @cached_property
    def text(self) -> builtins.str:
        """Return scalar Malloy syntax without executing it.

        Examples
        --------
        >>> import pymalloy as pm
        >>> (pm.col("amount") * 2).text
        '(amount * 2)'
        """
        return self._source if self._source is not None else render(self._node)

    def __repr__(self) -> builtins.str:
        return f"Expr({self.text!r})"

    def equals(self, other: Expr) -> bool:
        """Compare symbolic operation trees as a Python boolean.

        Parameters
        ----------
        other : Expr
            Expression to compare. Authored spelling and annotations are ignored.

        Returns
        -------
        bool
            Whether the operation trees match. This does not prove semantic
            equivalence. The ``==`` operator instead builds a Malloy predicate.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("amount").equals(pm.col("amount"))
        True
        >>> pm.col("amount").equals(pm.col("refund"))
        False
        """
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

    # Equality constructs syntax. equals() performs structural comparison.
    # pyrefly: ignore[bad-override]
    def __eq__(self, other: IntoExpr) -> Expr:  # ty: ignore[invalid-method-override] # pyright: ignore[reportIncompatibleMethodOverride]
        return self._binary("=", other)

    # pyrefly: ignore[bad-override]
    def __ne__(self, other: IntoExpr) -> Expr:  # ty: ignore[invalid-method-override] # pyright: ignore[reportIncompatibleMethodOverride]
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
        """Test whether a value is null.

        Returns
        -------
        Expr
            A boolean predicate for where, having, or case.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("amount").is_null().text
        '(amount is null)'
        """
        return self._with_node(ScalarNullTest(value=self._node, negated=False))

    def is_not_null(self) -> Expr:
        """Test whether a value is not null.

        Returns
        -------
        Expr
            A boolean predicate for where, having, or case.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("amount").is_not_null().text
        '(amount is not null)'
        """
        return self._with_node(ScalarNullTest(value=self._node, negated=True))

    def fill_null(self, value: IntoExpr) -> Expr:
        """Replace null values with another expression or scalar.

        Parameters
        ----------
        value : Expr or scalar
            Fallback value, with a compatible Malloy type.

        Returns
        -------
        Expr
            A new scalar expression. The original remains unchanged.

        Examples
        --------
        >>> import pymalloy as pm
        >>> expr = pm.col("amount").fill_null(0)
        >>> candidate = pm.draft().define(values=pm.sql("SELECT NULL::INTEGER AS amount"))
        >>> candidate = candidate.queries(result=pm.ref("values").pipe(pm.query(pm.select(amount=expr))))
        >>> pm.run(candidate).rows()
        [{'amount': 0}]
        """
        return self._binary("??", value)

    def nullif(self, value: IntoExpr) -> Expr:
        """Return null when this expression equals the supplied value.

        Parameters
        ----------
        value : Expr or scalar
            Value to compare, for example zero in a denominator.

        Returns
        -------
        Expr
            A new scalar expression. The original remains unchanged.

        Examples
        --------
        >>> import pymalloy as pm
        >>> expr = pm.col("amount").nullif(0)
        >>> candidate = pm.draft().define(values=pm.sql("SELECT 0::INTEGER AS amount"))
        >>> candidate = candidate.queries(result=pm.ref("values").pipe(pm.query(pm.select(amount=expr))))
        >>> pm.run(candidate).rows()
        [{'amount': None}]
        """
        return self._call("nullif", value)

    def _aggregate(self, name: builtins.str) -> Expr:
        if isinstance(self._node, ScalarField):
            return self._with_node(call(name, receiver=tuple(self._node.path))._node)
        return self._call(name)

    def sum(self) -> Expr:
        """Sum values using Malloy aggregate locality.

        Returns
        -------
        Expr
            An aggregate expression for measure or aggregate. Malloy resolves the
            field's source scope and type during compilation.

        See Also
        --------
        Expr.filter : Restrict this aggregate's input.
        count : Count source rows rather than distinct field values.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("amount").sum().text
        'amount.sum()'
        """
        return self._aggregate("sum")

    def avg(self) -> Expr:
        """Compute the arithmetic mean using Malloy aggregate locality.

        Returns
        -------
        Expr
            An aggregate expression for measure or aggregate. Malloy resolves the
            field's source scope and type during compilation.

        See Also
        --------
        Expr.filter : Restrict this aggregate's input.
        count : Count source rows rather than distinct field values.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("amount").avg().text
        'amount.avg()'
        """
        return self._aggregate("avg")

    def min(self) -> Expr:
        """Find the minimum value in each group.

        Returns
        -------
        Expr
            An aggregate expression for measure or aggregate. Malloy resolves the
            field's source scope and type during compilation.

        See Also
        --------
        Expr.filter : Restrict this aggregate's input.
        count : Count source rows rather than distinct field values.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("amount").min().text
        'amount.min()'
        """
        return self._aggregate("min")

    def max(self) -> Expr:
        """Find the maximum value in each group.

        Returns
        -------
        Expr
            An aggregate expression for measure or aggregate. Malloy resolves the
            field's source scope and type during compilation.

        See Also
        --------
        Expr.filter : Restrict this aggregate's input.
        count : Count source rows rather than distinct field values.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("amount").max().text
        'amount.max()'
        """
        return self._aggregate("max")

    def count_distinct(self) -> Expr:
        """Count distinct non-null values in each group.

        Returns
        -------
        Expr
            An aggregate expression for measure or aggregate. Malloy resolves the
            field's source scope and type during compilation.

        See Also
        --------
        Expr.filter : Restrict this aggregate's input.
        count : Count source rows rather than distinct field values.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("amount").count_distinct().text
        'count(amount)'
        """
        return self._call("count")

    def cast(self, type: builtins.str, *, safe: bool = False) -> Expr:
        """Convert a scalar to a Malloy or native SQL type.

        Parameters
        ----------
        type : str
            Nonempty type text, such as "number", "string", or a supported native
            SQL type. The compiler and engine decide which conversions are valid.
        safe : bool, default False
            Request a safe cast, yielding null for failed value conversions when
            supported by the dialect. Invalid type syntax can still fail compilation.

        Returns
        -------
        Expr
            A cast expression.

        Examples
        --------
        >>> import pymalloy as pm
        >>> expr = pm.lit("invalid").cast("number", safe=True)
        >>> candidate = pm.draft().define(values=pm.sql("SELECT 1 AS id"))
        >>> candidate = candidate.queries(result=pm.ref("values").pipe(pm.query(pm.select(value=expr))))
        >>> pm.run(candidate).rows()
        [{'value': None}]
        """
        if not isinstance(type, str) or not type.strip():
            raise ValueError("Cast type must contain a Malloy or native SQL type")
        return self._with_node(ScalarCast(value=self._node, type=type, safe=safe))

    def filter(self, predicate: Expr) -> Expr:
        """Restrict the input of this aggregate without filtering sibling aggregates.

        Parameters
        ----------
        predicate : Expr
            Boolean expression over input rows. The receiver must be an aggregate
            expression accepted by Malloy.

        Returns
        -------
        Expr
            A filtered aggregate for a measure or aggregate clause.

        See Also
        --------
        where : Filter input rows for the whole source/query.
        having : Filter aggregate output groups.

        Examples
        --------
        >>> import pymalloy as pm
        >>> north = pm.col("amount").sum().filter(pm.col("region") == "North")
        >>> measures = pm.measure(north_revenue=north, all_revenue=pm.col("amount").sum())
        >>> measures.names
        ('north_revenue', 'all_revenue')
        """
        if not isinstance(predicate, Expr):
            raise TypeError("An aggregate filter requires an Expr predicate")
        return self._with_node(
            ScalarFilter(value=self._node, predicate=predicate._node)
        )

    def asc(self) -> Sort:
        """Sort this expression in ascending order.

        Returns
        -------
        Sort
            Ordering metadata accepted by order_by, not a scalar result.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("amount").asc().text
        'amount asc'
        """
        return Sort(self, descending=False)

    def desc(self) -> Sort:
        """Sort this expression in descending order.

        Returns
        -------
        Sort
            Ordering metadata accepted by order_by, not a scalar result.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("amount").desc().text
        'amount desc'
        """
        return Sort(self, descending=True)

    @property
    def str(self) -> StringExpr:
        """Access string operations for this expression.

        Returns
        -------
        StringExpr
            Namespace whose methods produce ordinary composable Expr values.

        Examples
        --------
        >>> import pymalloy as pm
        >>> expression = pm.col("name").str.strip().str.lower()
        >>> isinstance(expression, pm.Expr)
        True
        """
        return StringExpr(self)

    @property
    def dt(self) -> DateTimeExpr:
        """Access temporal operations for this expression.

        Returns
        -------
        DateTimeExpr
            Namespace whose methods produce ordinary composable Expr values.

        Examples
        --------
        >>> import pymalloy as pm
        >>> expression = pm.col("created_at").dt.year()
        >>> isinstance(expression, pm.Expr)
        True
        """
        return DateTimeExpr(self)


@dataclass(frozen=True, eq=False)
class Sort(NotebookDisplay):
    """An expression and direction for an order_by clause.

    Parameters
    ----------
    expression : Expr
        Output field/expression to order.
    descending : bool, default False
        True for descending order. Usually create this with Expr.asc or Expr.desc.

    Examples
    --------
    >>> import pymalloy as pm
    >>> pm.order_by(pm.col("revenue").desc(), pm.col("region").asc()).text
    'order_by: revenue desc, region asc'
    """

    expression: Expr
    descending: bool = False

    @property
    def text(self) -> builtins.str:
        """Return the expression followed by its explicit sort direction."""
        return self.expression.text + (" desc" if self.descending else " asc")


def _expr(value: IntoExpr) -> Expr:
    return value if isinstance(value, Expr) else lit(value)


def col(*path: str) -> Expr:
    """Reference a field using explicit path components.

    Parameters
    ----------
    *path : str
        One or more field identifiers. Pass separate components for joins or
        nested records: ``col("customer", "name")``. A dot inside a single
        string is part of that identifier and is quoted when necessary.

    Returns
    -------
    Expr
        A reference whose existence and type are checked by Malloy.

    See Also
    --------
    ref : Reference a source or query instead of a scalar field.
    lit : Represent a literal value rather than a field name.

    Examples
    --------
    >>> import pymalloy as pm
    >>> pm.col("customer", "name").text
    'customer.name'
    >>> pm.col("customer.name").text
    '`customer.name`'
    >>> pm.col("amount").sum().text
    'amount.sum()'
    """
    if not path:
        raise ValueError("A column requires at least one path component")
    for name in path:
        identifier(name)
    return Expr._from_node(ScalarField(path=path))


def given(name: str) -> Expr:
    r"""Reference a typed parameter declared in the Malloy model.

    Parameters
    ----------
    name : str
        Identifier without the ``$`` prefix. The model must declare this given.

    Returns
    -------
    Expr
        A parameter reference. Bind its value with ``givens=`` on sql/run/preview.

    Notes
    -----
    The installed compiler currently requires the experimental givens flag.
    Constructing a reference does not add a declaration or default value.

    Examples
    --------
    >>> import pymalloy as pm
    >>> source = "##! experimental.givens\ngiven: minimum :: number is 0\n"
    >>> candidate = pm.draft(source).define(values=pm.sql("SELECT 42 AS amount"))
    >>> candidate = candidate.queries(filtered=pm.ref("values").pipe(pm.query(
    ...     pm.where(pm.col("amount") > pm.given("minimum")),
    ...     pm.select(pm.col("amount")),
    ... )))
    >>> pm.run(candidate, givens={"minimum": 40}).rows()
    [{'amount': 42}]
    """
    if not isinstance(name, str) or not name.isidentifier():
        raise ValueError("A given requires an identifier name")
    return Expr._from_node(ScalarGiven(name=name))


def lit(value: Literal) -> Expr:
    """Create a literal scalar while retaining its Python value's meaning.

    Parameters
    ----------
    value : scalar
        String, integer, finite float or Decimal, boolean, date, datetime, or
        None. Lists and dictionaries are not scalar literals. Aware datetimes
        preserve their instant when rendered. Nonfinite numbers are rejected.

    Returns
    -------
    Expr
        A literal expression. Strings are values, never implicit field names.

    See Also
    --------
    col : Reference a field.
    number : Preserve an authored numeric spelling such as ``1e0``.
    given : Bind parameters at query preparation time.

    Examples
    --------
    >>> import pymalloy as pm
    >>> pm.lit(True).text
    'true'
    >>> pm.lit(None).text
    'null'
    >>> (pm.col("region") == "North").equals(pm.col("region") == pm.lit("North"))
    True
    """
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
    """Preserve a finite numeric literal's exact Malloy spelling.

    Parameters
    ----------
    text : str
        One numeric token, including optional sign, decimal fraction, and
        exponent. Expressions, whitespace, NaN, and infinity are rejected.

    Returns
    -------
    Expr
        A numeric literal retaining its spelling for Malloy type inference.

    Notes
    -----
    Use lit for ordinary Python numbers. Use number when reconstructing source
    where changing ``1e0`` into ``1`` could change the result type.

    Examples
    --------
    >>> import pymalloy as pm
    >>> pm.number("1e0").text
    '1e0'
    >>> pm.number("-0.00").text
    '-0.00'
    """
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
    """Embed scalar Malloy syntax outside the symbolic constructors.

    Parameters
    ----------
    code : str
        Nonempty scalar expression text. It is retained verbatim and checked
        when the enclosing model compiles. It is trusted code, not escaped data.

    Returns
    -------
    Expr
        An opaque scalar that still composes with symbolic operators.

    See Also
    --------
    syntax : Embed source or query grammar rather than a scalar expression.
    lit : Encode a Python value safely as a literal.

    Examples
    --------
    >>> import pymalloy as pm
    >>> expression = pm.raw_expr("amount * 0.9")
    >>> expression.text
    'amount * 0.9'
    """
    if not isinstance(code, str) or not code.strip():
        raise ValueError("A raw expression requires Malloy text")
    return Expr._from_node(ScalarRaw(code=code))


def call(name: str, *args: IntoExpr, receiver: tuple[str, ...] | None = None) -> Expr:
    """Construct a Malloy function call with optional source scope.

    Parameters
    ----------
    name : str
        Function identifier. Availability and argument types are checked by Malloy.
    *args : Expr or scalar
        Arguments. Python scalar values are converted with lit.
    receiver : tuple of str, optional
        Nonempty source/field path for a receiver call. Use separate path
        components. An omitted receiver constructs a global function call.

    Returns
    -------
    Expr
        A symbolic call. Prefer named expression methods for common operations.

    Examples
    --------
    >>> import pymalloy as pm
    >>> pm.call("abs", pm.col("amount")).text
    'abs(amount)'
    >>> pm.call("count", receiver=("orders",)).text
    'orders.count()'
    """
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
    """Count source rows, optionally at a joined source's scope.

    Parameters
    ----------
    *scope : str
        Source path components. With no components, count the current source's
        rows. To count distinct field values, use ``col(...).count_distinct()``.

    Returns
    -------
    Expr
        A row-count aggregate resolved with Malloy's relationship semantics.

    Examples
    --------
    >>> import pymalloy as pm
    >>> pm.count().text
    'count()'
    >>> pm.count("orders").text
    'orders.count()'
    """
    return call("count", receiver=scope or None)


def case(*branches: tuple[Expr, IntoExpr], otherwise: IntoExpr) -> Expr:
    """Choose the first matching value from ordered conditions.

    Parameters
    ----------
    *branches : tuple of (Expr, Expr or scalar)
        One or more condition/result pairs in priority order. Conditions must
        be symbolic predicates. Scalar results are converted with lit.
    otherwise : Expr or scalar
        Required fallback when no condition matches. Use None for a null fallback.

    Returns
    -------
    Expr
        A Malloy pick expression whose result types must be compatible.

    Examples
    --------
    >>> import pymalloy as pm
    >>> band = pm.case((pm.col("amount") >= 100, "large"), otherwise="small")
    >>> band.equals(pm.case((pm.col("amount") >= 100, "large"), otherwise="small"))
    True
    """
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
    """Namespace for string operations, available through ``Expr.str``.

    Methods return Expr values. Malloy checks the receiver's type at compilation.

    Examples
    --------
    >>> import pymalloy as pm
    >>> expression = pm.col("name").str.strip().str.lower()
    >>> isinstance(expression, pm.Expr)
    True
    """

    expression: Expr

    def lower(self) -> Expr:
        """Convert text to lowercase.

        Returns
        -------
        Expr
            Symbolic string operation resolved by Malloy.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("name").str.lower().text
        'lower(name)'
        """
        return self.expression._call("lower")

    def upper(self) -> Expr:
        """Convert text to uppercase.

        Returns
        -------
        Expr
            Symbolic string operation resolved by Malloy.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("name").str.upper().text
        'upper(name)'
        """
        return self.expression._call("upper")

    def length(self) -> Expr:
        """Count characters in text.

        Returns
        -------
        Expr
            Symbolic string operation resolved by Malloy.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("name").str.length().text
        'length(name)'
        """
        return self.expression._call("length")

    def contains(self, value: IntoExpr) -> Expr:
        """Test for a literal substring.

        Parameters
        ----------
        value : Expr or scalar
            Literal text or a string expression. Matching is case-sensitive.
            This API does not interpret regular-expression syntax.

        Returns
        -------
        Expr
            A boolean predicate. Combine with str.lower for normalized matching.

        Examples
        --------
        >>> import pymalloy as pm
        >>> matched = pm.col("name").str.contains("Ada")
        >>> isinstance(matched, pm.Expr)
        True
        """
        return self.expression._call("strpos", value) > 0

    def starts_with(self, value: IntoExpr) -> Expr:
        """Test whether text starts with a prefix.

        Parameters
        ----------
        value : Expr or scalar
            Literal text or a string expression. Matching is case-sensitive.
            This API does not interpret regular-expression syntax.

        Returns
        -------
        Expr
            A boolean predicate. Combine with str.lower for normalized matching.

        Examples
        --------
        >>> import pymalloy as pm
        >>> matched = pm.col("name").str.starts_with("Ada")
        >>> isinstance(matched, pm.Expr)
        True
        """
        return self.expression._call("starts_with", value)

    def ends_with(self, value: IntoExpr) -> Expr:
        """Test whether text ends with a suffix.

        Parameters
        ----------
        value : Expr or scalar
            Literal text or a string expression. Matching is case-sensitive.
            This API does not interpret regular-expression syntax.

        Returns
        -------
        Expr
            A boolean predicate. Combine with str.lower for normalized matching.

        Examples
        --------
        >>> import pymalloy as pm
        >>> matched = pm.col("name").str.ends_with("Ada")
        >>> isinstance(matched, pm.Expr)
        True
        """
        return self.expression._call("ends_with", value)

    def strip(self) -> Expr:
        """Trim leading and trailing spaces using SQL trim semantics.

        Returns
        -------
        Expr
            Symbolic string operation resolved by Malloy.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("name").str.strip().text
        'trim(name)'
        """
        return self.expression._call("trim")

    def replace(self, old: IntoExpr, new: IntoExpr) -> Expr:
        """Replace literal occurrences in a string.

        Parameters
        ----------
        old : Expr or scalar
            Literal substring or expression to find. This is not a regex pattern.
        new : Expr or scalar
            Replacement text or string expression.

        Returns
        -------
        Expr
            A symbolic replace call resolved by Malloy.

        Examples
        --------
        >>> import pymalloy as pm
        >>> expression = pm.col("name").str.replace(" ", "_")
        >>> isinstance(expression, pm.Expr)
        True
        """
        return self.expression._call("replace", old, new)


_TIME_UNITS = frozenset(
    {"year", "quarter", "month", "week", "day", "hour", "minute", "second"}
)


@dataclass(frozen=True, eq=False)
class DateTimeExpr:
    """Namespace for temporal operations, available through ``Expr.dt``.

    Methods return Expr values. Malloy checks the receiver's type at compilation.

    Examples
    --------
    >>> import pymalloy as pm
    >>> expression = pm.col("created_at").dt.year()
    >>> isinstance(expression, pm.Expr)
    True
    """

    expression: Expr

    def year(self) -> Expr:
        """Extract the calendar year from a temporal expression.

        Returns
        -------
        Expr
            Numeric component. The input must be a date/timestamp supporting this
            component in Malloy. Use truncate to group by complete time periods.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("created_at").dt.year().text
        'year(created_at)'
        """
        return self.expression._call("year")

    def month(self) -> Expr:
        """Extract the month number from a temporal expression.

        Returns
        -------
        Expr
            Numeric component. The input must be a date/timestamp supporting this
            component in Malloy. Use truncate to group by complete time periods.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("created_at").dt.month().text
        'month(created_at)'
        """
        return self.expression._call("month")

    def day(self) -> Expr:
        """Extract the day of the month from a temporal expression.

        Returns
        -------
        Expr
            Numeric component. The input must be a date/timestamp supporting this
            component in Malloy. Use truncate to group by complete time periods.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("created_at").dt.day().text
        'day(created_at)'
        """
        return self.expression._call("day")

    def hour(self) -> Expr:
        """Extract the hour component from a temporal expression.

        Returns
        -------
        Expr
            Numeric component. The input must be a date/timestamp supporting this
            component in Malloy. Use truncate to group by complete time periods.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("created_at").dt.hour().text
        'hour(created_at)'
        """
        return self.expression._call("hour")

    def minute(self) -> Expr:
        """Extract the minute component from a temporal expression.

        Returns
        -------
        Expr
            Numeric component. The input must be a date/timestamp supporting this
            component in Malloy. Use truncate to group by complete time periods.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("created_at").dt.minute().text
        'minute(created_at)'
        """
        return self.expression._call("minute")

    def second(self) -> Expr:
        """Extract the second component from a temporal expression.

        Returns
        -------
        Expr
            Numeric component. The input must be a date/timestamp supporting this
            component in Malloy. Use truncate to group by complete time periods.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("created_at").dt.second().text
        'second(created_at)'
        """
        return self.expression._call("second")

    def truncate(self, unit: str) -> Expr:
        """Truncate a temporal value to the start of a time period.

        Parameters
        ----------
        unit : {"year", "quarter", "month", "week", "day", "hour", "minute", "second"}
            Period boundary. Valid units for a particular date/timestamp are
            checked by Malloy. Timezone interpretation follows the query/runtime.

        Returns
        -------
        Expr
            A period value suitable for group_by. Unlike extracting a month number,
            truncating to month retains the year and distinguishes Januarys.

        Examples
        --------
        >>> import pymalloy as pm
        >>> monthly = pm.group_by(month=pm.col("created_at").dt.truncate("month"))
        >>> monthly.names
        ('month',)
        """
        if unit not in _TIME_UNITS:
            raise ValueError(
                "Choose year, quarter, month, week, day, hour, minute, or second"
            )
        return self.expression._with_node(
            ScalarTruncate(value=self.expression._node, unit=unit)
        )

    def date(self) -> Expr:
        """Cast a temporal expression to a date.

        Returns
        -------
        Expr
            A date cast, interpreted using the query/runtime timezone for timestamps.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.col("created_at").dt.date().equals(pm.col("created_at").cast("date"))
        True
        """
        return self.expression.cast("date")
