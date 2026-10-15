r"""Build immutable Malloy sources, reusable views, and editable model drafts.

Source methods declare fields, joins, and saved views. View methods describe a
query stage. Malloy resolves their names, types, and execution semantics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Self

from pymalloy._authoring.identifiers import identifier
from pymalloy._authoring.syntax import (
    Syntax as _Syntax,
)
from pymalloy._authoring.syntax import (
    _notes,
    binding,
    block,
    construct,
    named_clause,
)
from pymalloy._authoring.syntax import (
    scalar_expression as _scalar,
)
from pymalloy._authoring.tables import TableReference, table_path
from pymalloy._model import DEFAULT_CONNECTION
from pymalloy._model.inputs import Input, snapshot_data
from pymalloy._protocol.records import SyntaxOperationKind
from pymalloy.expressions import Expr, Sort, col

__all__ = [
    "Draft",
    "Input",
    "Source",
    "View",
    "data",
    "draft",
    "read_model",
    "source",
    "sql",
    "table",
    "view",
]


def _append_clause(node: _Syntax, clause: _Syntax) -> _Syntax:
    if node._layout:
        return block((*node._fragments, clause))
    parts = list(node.parts)
    if not parts or not isinstance(parts[-1], str) or "}" not in parts[-1]:
        raise ValueError("A query block requires a closing brace")
    closing = parts.pop()
    assert isinstance(closing, str)
    before, brace, after = closing.rpartition("}")
    return _Syntax(
        (*parts, before, "\n  ", clause, "\n" + brace + after),
        _operation=node._operation,
    )


class _Builder(_Syntax):
    @classmethod
    def raw(cls, *parts: str | Source | View | Expr) -> Self:
        r"""Concatenate trusted Malloy text and authored values verbatim.

        Parameters
        ----------
        *parts : str, Source, View, or Expr
            Syntax pieces, including required spaces and punctuation. Malloy checks
            the resulting text when a model compiles.

        Returns
        -------
        Source or View
            An immutable expression retaining captured inputs from its parts.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.Source.raw("orders").text
        'orders'
        >>> pm.View.raw("{ select: * }").text
        '{ select: * }'
        """
        if not all(isinstance(part, (str, Source, View, Expr)) for part in parts):
            raise TypeError("Raw parts require text, Source, View, or Expr values")
        return cls(tuple(parts))

    def pipe(self, *stages: View | str) -> Self:
        r"""Apply successive query stages.

        Parameters
        ----------
        *stages : View or str
            Views in pipeline order. A string names a saved view. With no stages,
            return this value unchanged.

        Returns
        -------
        Source or View
            A new pipeline of the receiver's type.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.source("orders").pipe("by_region", pm.view().select("region")).text
        'orders -> by_region -> {\n  select: region\n}'
        """
        if not stages:
            return self
        notes, value = _notes(self)
        parts: list[str | _Syntax] = []
        for stage in stages:
            parts.extend((" -> ", _view(stage)))
        result = construct("pipe", value, *parts)
        return self._from_syntax(
            _Syntax((*notes, result), _layout=True) if notes else result
        )


class Source(_Builder):
    r"""An immutable relation expression with source declarations and pipelines.

    Construct with table, sql, data, source, or Source.raw. Declaration methods
    append to one trailing ``extend`` block. Each method returns a new Source.

    Examples
    --------
    >>> import pymalloy as pm
    >>> orders = pm.table("orders.parquet").measure(revenue=pm.col("amount").sum())
    >>> orders.names
    ('revenue',)
    """

    def _add(self, clause: _Syntax) -> Source:
        notes, value = _notes(self)
        assert isinstance(value, _Syntax)
        children = value._fragments
        if (
            value._operation
            and value._operation.kind == "extend"
            and children
            and children[-1]._operation
            and children[-1]._operation.kind == "block"
        ):
            trailing = children[-1]
            result = _Syntax(
                tuple(
                    _append_clause(trailing, clause) if part is trailing else part
                    for part in value.parts
                ),
                _operation=value._operation,
                _layout=value._layout,
            )
        else:
            result = construct("extend", value, " extend ", block((clause,)))
        return Source._from_syntax(
            _Syntax((*notes, result), _layout=True) if notes else result
        )

    def dimension(self, /, **fields: Expr) -> Source:
        r"""Declare row-level fields.

        Parameters
        ----------
        **fields : Expr
            Names mapped to scalar expressions.

        Returns
        -------
        Source
            A new source with the declarations appended.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.table("orders").dimension(net=pm.col("amount") - pm.col("refund")).names
        ('net',)
        """
        return self._add(named_clause("dimension", fields))

    def measure(self, /, **fields: Expr) -> Source:
        r"""Declare reusable aggregate fields.

        Parameters
        ----------
        **fields : Expr
            Names mapped to aggregate expressions. Attach units with Expr.doc.

        Returns
        -------
        Source
            A new source with the declarations appended.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.table("orders").measure(revenue=pm.col("amount").sum()).names
        ('revenue',)
        """
        return self._add(named_clause("measure", fields))

    def view(self, /, **views: View) -> Source:
        r"""Declare reusable source-relative views.

        Parameters
        ----------
        **views : View
            Names mapped to views created with view or View.raw.

        Returns
        -------
        Source
            A new source retaining each view's editing scope.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.table("orders").view(totals=pm.view().aggregate(n=pm.count())).names
        ('totals',)
        """
        if not all(isinstance(value, View) for value in views.values()):
            raise TypeError("Source.view requires View values")
        return self._add(named_clause("view", views, kind="query"))

    def primary_key(self, field: str) -> Source:
        r"""Declare the field identifying one source row.

        Parameters
        ----------
        field : str
            One field identifier. Validate uniqueness and nulls in the data before
            relying on this declaration for aggregate locality.

        Returns
        -------
        Source
            A new source with the key declaration appended.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.table("orders").primary_key("order_id").text.splitlines()[1]
        '  primary_key: order_id'
        """
        return self._add(
            construct(
                "primary_key", "primary_key: ", identifier(field), arguments=(field,)
            )
        )

    def _join(self, kind: str, name: str, source: Source, on: Expr | None) -> Source:
        if not isinstance(source, Source):
            raise TypeError("Joins require a Source")
        if on is None and kind != "cross":
            raise TypeError("A join predicate requires an Expr")
        value = binding("source", name, source)
        if on is not None:
            value = _Syntax(
                (*value.parts, " on ", _Syntax((_scalar(on),), kind="clause")),
                kind="source",
                name=name,
                _layout=True,
            )
        return self._add(_Syntax((f"join_{kind}: ", value), _layout=True))

    def join_one(self, name: str, source: Source, *, on: Expr) -> Source:
        r"""Declare a relationship with one related row.

        Parameters
        ----------
        name : str
            Joined source name for field paths.
        source : Source
            Related relation expression.
        on : Expr
            Join predicate. Qualify joined fields with col(name, field).

        Returns
        -------
        Source
            A new source. Malloy resolves the relationship and aggregate locality.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.table("orders").join_one("labels", pm.source("labels"), on=pm.lit(True)).names
        ('labels',)
        """
        return self._join("one", name, source, on)

    def join_many(self, name: str, source: Source, *, on: Expr) -> Source:
        r"""Declare a relationship with multiple related rows.

        Parameters
        ----------
        name : str
            Joined source name for field paths.
        source : Source
            Related relation expression.
        on : Expr
            Join predicate. Qualify joined fields with col(name, field).

        Returns
        -------
        Source
            A new source. Malloy resolves the relationship and aggregate locality.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.table("orders").join_many("labels", pm.source("labels"), on=pm.lit(True)).names
        ('labels',)
        """
        return self._join("many", name, source, on)

    def join_cross(
        self, name: str, source: Source, *, on: Expr | None = None
    ) -> Source:
        r"""Declare a relationship with a cross product.

        Parameters
        ----------
        name : str
            Joined source name for field paths.
        source : Source
            Related relation expression.
        on : Expr, optional
            Join predicate. Qualify joined fields with col(name, field). An omitted predicate includes every pair.

        Returns
        -------
        Source
            A new source. Malloy resolves the relationship and aggregate locality.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.table("orders").join_cross("labels", pm.source("labels"), on=pm.lit(True)).names
        ('labels',)
        """
        return self._join("cross", name, source, on)

    def where(self, predicate: Expr) -> Source:
        r"""Filter source rows before query stages.

        Parameters
        ----------
        predicate : Expr
            Boolean condition. Strings are literal values beside expressions.

        Returns
        -------
        Source
            A new source with a filter appended to its extension.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.table("orders").where(pm.col("amount") > 0).text.splitlines()[1]
        '  where: (amount > 0)'
        """
        return self._add(construct("where", "where: ", _scalar(predicate)))


class View(_Builder):
    r"""An immutable source-relative query stage.

    Construct with view or View.raw. Clauses append to the final stage. Calling
    pipe starts a new stage. Positional strings in group_by, aggregate, select,
    and order_by name field paths split on dots. Keyword values require Expr.
    col(*path) preserves explicit components, including literal dots.

    Examples
    --------
    >>> import pymalloy as pm
    >>> pm.view().group_by("customer.name").aggregate(n=pm.count()).text
    '{\n  group_by: customer.name\n  aggregate: n is count()\n}'
    """

    def _add(self, clause: _Syntax) -> View:
        notes, value = _notes(self)
        assert isinstance(value, _Syntax)
        if value._operation and value._operation.kind == "pipe":
            parts = list(value.parts)
            index = next(
                i
                for i in range(len(parts) - 1, -1, -1)
                if isinstance(parts[i], _Syntax)
            )
            stage = parts[index]
            assert isinstance(stage, _Syntax)
            parts[index] = View._from_syntax(stage)._add(clause)
            result = _Syntax(
                tuple(parts), _operation=value._operation, _layout=value._layout
            )
        elif value._operation and value._operation.kind == "block":
            result = _append_clause(value, clause)
        else:
            result = _Syntax((value, " + ", block((clause,))), _layout=True)
        return View._from_syntax(
            _Syntax((*notes, result), _layout=True) if notes else result
        )

    def group_by(self, /, *fields: Expr | str, **named: Expr) -> View:
        r"""Choose the dimensions defining the output grain.

        Parameters
        ----------
        *fields : Expr or str
            Expressions or field paths. Strings split on dots, so "customer.name"
            means col("customer", "name"). Use col("customer.name") for a literal dot.
        **named : Expr
            Output names mapped to expressions. At least one field is required.

        Returns
        -------
        View
            A new view with the clause appended to its final stage.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.view().group_by("region").text
        '{\n  group_by: region\n}'
        """
        return self._add(_fields("group_by", fields, named))

    def aggregate(self, /, *fields: Expr | str, **named: Expr) -> View:
        r"""Choose aggregate values for each output group.

        Parameters
        ----------
        *fields : Expr or str
            Expressions or field paths. Strings split on dots, so "customer.name"
            means col("customer", "name"). Use col("customer.name") for a literal dot.
        **named : Expr
            Output names mapped to expressions. At least one field is required.

        Returns
        -------
        View
            A new view with the clause appended to its final stage.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.view().aggregate("region").text
        '{\n  aggregate: region\n}'
        """
        return self._add(_fields("aggregate", fields, named))

    def select(self, /, *fields: Expr | str, **named: Expr) -> View:
        r"""Project row-level fields.

        Parameters
        ----------
        *fields : Expr or str
            Expressions or field paths. Strings split on dots, so "customer.name"
            means col("customer", "name"). Use col("customer.name") for a literal dot.
        **named : Expr
            Output names mapped to expressions. At least one field is required.

        Returns
        -------
        View
            A new view with the clause appended to its final stage.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.view().select("region").text
        '{\n  select: region\n}'
        """
        return self._add(_fields("select", fields, named))

    def where(self, predicate: Expr) -> View:
        r"""Filter rows before aggregation.

        Parameters
        ----------
        predicate : Expr
            Symbolic boolean condition. Combine comparisons with &, |, and ~.

        Returns
        -------
        View
            A new view with the filter appended to its final stage.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.view().where(pm.col("amount") > 0).text
        '{\n  where: (amount > 0)\n}'
        """
        return self._add(construct("where", "where: ", _scalar(predicate)))

    def having(self, predicate: Expr) -> View:
        r"""Filter groups using aggregate values.

        Parameters
        ----------
        predicate : Expr
            Symbolic boolean condition. Combine comparisons with &, |, and ~.

        Returns
        -------
        View
            A new view with the filter appended to its final stage.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.view().having(pm.col("amount") > 0).text
        '{\n  having: (amount > 0)\n}'
        """
        return self._add(construct("having", "having: ", _scalar(predicate)))

    def nest(self, /, **views: View | str) -> View:
        r"""Add named nested query results.

        Parameters
        ----------
        **views : View or str
            Output names mapped to views. A string names a saved view.

        Returns
        -------
        View
            A new view retaining each nested view's scope.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.view().nest(details="detail").names
        ('details',)
        """
        return self._add(
            named_clause(
                "nest",
                {name: _view(value) for name, value in views.items()},
                kind="query",
            )
        )

    def order_by(self, *fields: Expr | Sort | str) -> View:
        r"""Order output fields, with optional explicit directions.

        Parameters
        ----------
        *fields : Expr, Sort, or str
            Expressions, asc/desc values, or field paths split on dots. At least
            one field is required. A bare field uses Malloy's default direction.

        Returns
        -------
        View
            A new view with ordering appended to its final stage.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.view().order_by(pm.col("revenue").desc(), "region").text
        '{\n  order_by: revenue desc, region\n}'
        """
        if not fields:
            raise ValueError("order_by requires fields")
        parts: list[str | _Syntax | Expr] = ["order_by: "]
        for index, field in enumerate(fields):
            if index:
                parts.append(", ")
            if isinstance(field, Sort):
                direction = "desc" if field.descending else "asc"
                parts.append(
                    construct(direction, _scalar(field.expression), " " + direction)
                )
            else:
                parts.append(_field(field))
        return self._add(construct("order_by", *parts))

    def limit(self, rows: int) -> View:
        r"""Bound the output row count of the final stage.

        Parameters
        ----------
        rows : int
            Nonnegative count. Booleans are rejected. Pair with order_by when
            selecting a deterministic top-N result.

        Returns
        -------
        View
            A new view. The limit bounds output, not input scanning cost.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.view().limit(3).text
        '{\n  limit: 3\n}'
        """
        if type(rows) is not int or rows < 0:
            raise ValueError("Limit must be a nonnegative integer")
        return self._add(construct("limit", f"limit: {rows}", arguments=(str(rows),)))


def _view(value: View | str) -> View:
    if isinstance(value, str):
        return View._from_syntax(
            construct("ref", identifier(value), arguments=(value,))
        )
    if not isinstance(value, View):
        raise TypeError("Query stages require a View or saved view name")
    return value


def _field(value: Expr | str) -> Expr:
    return col(*value.split(".")) if isinstance(value, str) else _scalar(value)


def _fields(
    keyword: SyntaxOperationKind, fields: tuple[Expr | str, ...], named: dict[str, Expr]
) -> _Syntax:
    values: list[_Syntax | Expr] = [_field(field) for field in fields]
    values.extend(binding("field", name, value) for name, value in named.items())
    if not values:
        raise ValueError(f"{keyword} requires fields")
    parts: list[str | _Syntax | Expr] = [keyword + ": "]
    for index, value in enumerate(values):
        if index:
            parts.append(", ")
        parts.append(value)
    return construct(keyword, *parts)


def table(path: str | Path, *, connection: str = DEFAULT_CONNECTION) -> Source:
    r"""Reference a database table or a file readable by the connection.

    Parameters
    ----------
    path : str or pathlib.Path
        A string is a native DuckDB table/file reference, kept relative when
        supplied that way. A Path becomes an absolute file reference. Strings
        can also name HTTP(S) files when the runtime supports remote access.
    connection : str, default "duckdb"
        Malloy connection name. Match the connection's ``name``.

    Returns
    -------
    Source
        An unnamed source expression. Bind it with ``draft().sources(...)``.

    Notes
    -----
    Construction neither reads the file nor discovers its schema. Native DuckDB
    resolves catalog names before files and checks the working directory before
    ``file_search_path``. Loading a model does not change the data root.

    See Also
    --------
    data : Capture materialized Python data.
    sql : Define a source using SQL.

    Examples
    --------
    >>> import pymalloy as pm
    >>> source = pm.table("orders.parquet").measure(revenue=pm.col("amount").sum())
    >>> candidate = pm.draft().sources(orders=source)
    >>> candidate.names
    ('orders',)
    """
    return Source((TableReference(connection, table_path(path)),))


def data(
    frame: Any, *, name: str | None = None, connection: str = DEFAULT_CONNECTION
) -> Source:
    r"""Capture Python dataframe values as a portable Malloy source.

    Use this when Python prepares the input and Malloy supplies the semantic
    model. Capture once, then reuse the returned source in several drafts.

    Parameters
    ----------
    frame : dataframe-like
        Materialized Arrow-compatible data, such as a Polars DataFrame or
        PyArrow Table. Inputs must have unique field names and portable types.
        Collect lazy frames explicitly before passing them here.
    name : str, optional
        Logical input name used by Python reconstruction. An omitted name is
        generated. Distinct captures in one model must have distinct names.
    connection : str, default "duckdb"
        Malloy connection name. Match the connection's ``name``.

    Returns
    -------
    Source
        Source backed by an immutable Arrow snapshot. Later changes to the
        producer do not change this source.

    Notes
    -----
    Requires PyArrow, installed directly with ``pip install pyarrow`` or supplied
    by ``pymalloy[headless]``. Verified Parquet is materialized on demand and
    retained by the draft/model that uses it. A widget sends those bytes to the
    browser. Use ``pymalloy.export.bundle`` to persist a portable model and
    its inputs. Keep preparation logic in the producing notebook or script.

    Examples
    --------
    >>> import pymalloy as pm
    >>> import polars as pl
    >>> frame = pl.DataFrame({"region": ["North", "North"], "amount": [20, 22]})
    >>> source = pm.data(frame, name="orders")
    >>> source.inputs[0].rows
    2
    >>> source.inputs[0].to_arrow().to_pylist() == frame.to_dicts()
    True
    """
    captured = snapshot_data(frame, name=name)
    return Source((TableReference(connection, captured.reference, data=captured),))


def sql(text: str, *, connection: str = DEFAULT_CONNECTION) -> Source:
    r"""Define an unnamed source using a SQL query.

    Parameters
    ----------
    text : str
        SQL evaluated by the data engine. This is SQL source code, not a
        parameterized query. Do not interpolate untrusted values into it.
    connection : str, default "duckdb"
        Malloy connection name used for discovery and execution.

    Returns
    -------
    Source
        Source expression whose schema is discovered when the model compiles.

    See Also
    --------
    table : Reference an existing table or file.
    given : Reference a typed Malloy parameter.

    Examples
    --------
    >>> import pymalloy as pm
    >>> candidate = pm.draft().sources(values=pm.sql("SELECT 42 AS answer"))
    >>> candidate = candidate.queries(answer=pm.source("values").pipe(
    ...     pm.view().select(pm.col("answer"))
    ... ))
    >>> pm.connect().model(candidate).query().run().to_pylist()
    [{'answer': 42}]
    """
    return Source._from_syntax(
        construct(
            "sql",
            f"{identifier(connection)}.sql({json.dumps(text, ensure_ascii=False)})",
            arguments=(text, connection),
        )
    )


def source(name: str) -> Source:
    r"""Reference a named source or query in a model.

    Parameters
    ----------
    name : str
        One Malloy identifier. Dots in this string are part of the identifier,
        not a field path. Use ``col`` for scalar field paths.

    Returns
    -------
    Source
        A reference resolved by Malloy during compilation.

    Examples
    --------
    >>> import pymalloy as pm
    >>> regional = pm.source("orders").pipe("by_region")
    >>> regional.text
    'orders -> by_region'
    """
    return Source._from_syntax(construct("ref", identifier(name), arguments=(name,)))


def view(name: str | None = None) -> View:
    r"""Start a query stage, or reference a saved view to refine.

    Parameters
    ----------
    name : str, optional
        A saved view in the piped source, such as ``"by_region"``. Clauses added
        to a named view refine it with ``+``. Omit to start an empty stage.

    Returns
    -------
    View
        An immutable view. Chain clauses, then pass it to Source.pipe or Source.view.

    Examples
    --------
    >>> import pymalloy as pm
    >>> pm.view().select("amount").text
    '{\n  select: amount\n}'
    >>> pm.source("orders").pipe(pm.view("by_region").limit(3)).text
    'orders -> by_region + {\n  limit: 3\n}'
    """
    return View._from_syntax(block(())) if name is None else _view(name)


from pymalloy._authoring.draft import Draft, draft, read_model
