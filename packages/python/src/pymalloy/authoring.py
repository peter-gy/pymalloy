"""Compose Malloy model syntax from symbolic scalar expressions and query clauses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pymalloy._authoring.identifiers import identifier
from pymalloy._authoring.syntax import (
    Fragment,
    binding,
    block,
    construct,
    named_clause,
    syntax,
)
from pymalloy._authoring.syntax import (
    scalar_expression as _scalar,
)
from pymalloy._authoring.tables import TableReference, table_path
from pymalloy._model import DEFAULT_CONNECTION
from pymalloy._model.inputs import snapshot_data
from pymalloy._protocol.records import SyntaxOperationKind
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
    """Reference a database table or a file readable by the connection.

    Parameters
    ----------
    path : str or pathlib.Path
        A string is a native DuckDB table/file reference, kept relative when
        supplied that way. A Path becomes an absolute file reference. Strings
        can also name HTTP(S) files when the runtime supports remote access.
    connection : str, default "duckdb"
        Malloy connection name. Match the runtime's ``connection_name``.

    Returns
    -------
    Fragment
        An unnamed source expression. Bind it with ``draft().define(...)``.

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
    >>> source = pm.table("orders.parquet").extend(
    ...     pm.measure(revenue=pm.col("amount").sum())
    ... )
    >>> candidate = pm.draft().define(orders=source)
    >>> candidate.names
    ('orders',)
    """
    return syntax(TableReference(connection, table_path(path)))


def data(
    frame: Any, *, name: str | None = None, connection: str = DEFAULT_CONNECTION
) -> Fragment:
    """Capture Python dataframe values as a portable Malloy source.

    Use this when Python prepares the input and Malloy supplies the semantic
    model. Capture once, then reuse the returned fragment in several drafts.

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
        Malloy connection name. Match the runtime's ``connection_name``.

    Returns
    -------
    Fragment
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
    >>> source.inputs[0].arrow().to_pylist() == frame.to_dicts()
    True
    """
    captured = snapshot_data(frame, name=name)
    return syntax(TableReference(connection, captured.reference, data=captured))


def sql(text: str, *, connection: str = DEFAULT_CONNECTION) -> Fragment:
    """Define an unnamed source using a SQL query.

    Parameters
    ----------
    text : str
        SQL evaluated by the data engine. This is SQL source code, not a
        parameterized query. Do not interpolate untrusted values into it.
    connection : str, default "duckdb"
        Malloy connection name used for discovery and execution.

    Returns
    -------
    Fragment
        Source expression whose schema is discovered when the model compiles.

    See Also
    --------
    table : Reference an existing table or file.
    given : Reference a typed Malloy parameter.

    Examples
    --------
    >>> import pymalloy as pm
    >>> candidate = pm.draft().define(values=pm.sql("SELECT 42 AS answer"))
    >>> candidate = candidate.queries(answer=pm.ref("values").pipe(
    ...     pm.query(pm.select(pm.col("answer")))
    ... ))
    >>> pm.run(candidate).rows()
    [{'answer': 42}]
    """
    return construct(
        "sql",
        f"{identifier(connection)}.sql({json.dumps(text, ensure_ascii=False)})",
        arguments=(text, connection),
    )


def ref(name: str) -> Fragment:
    """Reference a named source, query, or view for source/query composition.

    Parameters
    ----------
    name : str
        One Malloy identifier. Dots in this string are part of the identifier,
        not a field path. Use ``col`` for scalar field paths.

    Returns
    -------
    Fragment
        A reference resolved by Malloy during compilation.

    Examples
    --------
    >>> import pymalloy as pm
    >>> regional = pm.ref("orders").pipe(pm.ref("by_region"))
    >>> regional.text
    'orders -> by_region'
    """
    return construct("ref", identifier(name), arguments=(name,))


def dimension(**fields: Expr) -> Fragment:
    """Define named row-level fields on a source.

    Parameters
    ----------
    **fields
        Field names mapped to scalar expressions. Values remain symbolic until Malloy resolves them.

    Returns
    -------
    Fragment
        A clause for source.extend(...).

    Examples
    --------
    >>> import pymalloy as pm
    >>> clause = pm.dimension(net=pm.col("amount") - pm.col("refund"))
    >>> expression = pm.table("orders.parquet").extend(clause)
    >>> expression.names
    ('net',)
    """
    return named_clause("dimension", fields)


def measure(**fields: Expr) -> Fragment:
    """Define reusable aggregate expressions on a source.

    Parameters
    ----------
    **fields
        Measure names mapped to aggregate expressions. Define units and denominators with .doc() on each expression.

    Returns
    -------
    Fragment
        A clause for source.extend(...).

    Examples
    --------
    >>> import pymalloy as pm
    >>> clause = pm.measure(revenue=pm.col("amount").sum().doc("Booked amount in USD."))
    >>> expression = pm.table("orders.parquet").extend(clause)
    >>> expression.names
    ('revenue',)
    """
    return named_clause("measure", fields)


def view(**queries: Fragment) -> Fragment:
    """Define reusable named query views on a source.

    Parameters
    ----------
    **queries
        View names mapped to query fragments. Apply a view with ref("source").pipe(ref("view")).

    Returns
    -------
    Fragment
        A clause for source.extend(...).

    Examples
    --------
    >>> import pymalloy as pm
    >>> clause = pm.view(totals=pm.query(pm.aggregate(total=pm.col("amount").sum())))
    >>> expression = pm.table("orders.parquet").extend(clause)
    >>> expression.names
    ('totals',)
    """
    return named_clause("view", queries, kind="query")


def query(*clauses: Fragment) -> Fragment:
    """Compose clauses into a reusable query block.

    Parameters
    ----------
    *clauses : Fragment
        Query clauses in authored order, such as group_by, aggregate, select,
        where, having, nest, order_by, and limit.

    Returns
    -------
    Fragment
        Query syntax. Pipe a source into it or bind it as a named view.

    Notes
    -----
    This builds syntax. ``Model.query`` instead selects a runnable query from
    an already compiled model.

    Examples
    --------
    >>> import pymalloy as pm
    >>> regional = pm.query(
    ...     pm.group_by(pm.col("region")),
    ...     pm.aggregate(revenue=pm.col("amount").sum()),
    ...     pm.order_by(pm.col("revenue").desc()),
    ... )
    >>> candidate = pm.draft().define(orders=pm.table("orders.parquet"))
    >>> candidate = candidate.queries(by_region=pm.ref("orders").pipe(regional))
    >>> candidate.names
    ('orders', 'by_region')
    """
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
    """Choose dimensions that define the output grain.

    Each distinct combination of grouping values produces a group. Combine with aggregate to compute measures at that grain.

    Parameters
    ----------
    *fields : Expr
        Expressions retaining Malloy's inferred output names.
    **named : Expr
        Output names mapped to expressions. At least one field is required.
        Strings are not column references. Write ``pm.col("field")``.

    Returns
    -------
    Fragment
        A clause accepted by ``pm.query``.

    See Also
    --------
    query, col

    Examples
    --------
    >>> import pymalloy as pm
    >>> clause = pm.group_by(pm.col("region"), month=pm.col("created_at").dt.truncate("month"))
    >>> clause.text.startswith("group_by: ")
    True
    """
    return _fields("group_by", fields, named)


def aggregate(*fields: Expr, **named: Expr) -> Fragment:
    """Choose aggregate values for each output group.

    Reference source measures or supply aggregate expressions directly. Without group_by, the query aggregates across its input.

    Parameters
    ----------
    *fields : Expr
        Expressions retaining Malloy's inferred output names.
    **named : Expr
        Output names mapped to expressions. At least one field is required.
        Strings are not column references. Write ``pm.col("field")``.

    Returns
    -------
    Fragment
        A clause accepted by ``pm.query``.

    See Also
    --------
    query, col

    Examples
    --------
    >>> import pymalloy as pm
    >>> clause = pm.aggregate(pm.col("revenue"), orders=pm.count())
    >>> clause.text.startswith("aggregate: ")
    True
    """
    return _fields("aggregate", fields, named)


def select(*fields: Expr, **named: Expr) -> Fragment:
    """Project row-level fields from a source.

    Use select for detail rows. Use group_by and aggregate when the question requires grouped summaries.

    Parameters
    ----------
    *fields : Expr
        Expressions retaining Malloy's inferred output names.
    **named : Expr
        Output names mapped to expressions. At least one field is required.
        Strings are not column references. Write ``pm.col("field")``.

    Returns
    -------
    Fragment
        A clause accepted by ``pm.query``.

    See Also
    --------
    query, col

    Examples
    --------
    >>> import pymalloy as pm
    >>> clause = pm.select(pm.col("order_id"), net=pm.col("amount") - pm.col("refund"))
    >>> clause.text.startswith("select: ")
    True
    """
    return _fields("select", fields, named)


def nest(**queries: Fragment) -> Fragment:
    """Add named nested query results to a query.

    Parameters
    ----------
    **queries
        Output names mapped to query fragments. Each nested query keeps its own grouping and ordering.

    Returns
    -------
    Fragment
        A clause for a query block.

    Examples
    --------
    >>> import pymalloy as pm
    >>> clause = pm.nest(detail=pm.query(pm.select(pm.col("order_id"))))
    >>> expression = pm.query(clause)
    >>> expression.names
    ('detail',)
    """
    return named_clause("nest", queries, kind="query")


def where(predicate: Expr) -> Fragment:
    """Filter source rows before aggregation.

    Parameters
    ----------
    predicate : Expr
        Symbolic boolean condition. Combine conditions with &, |, and ~, parenthesizing each comparison. Null predicates do not select a row.

    Returns
    -------
    Fragment
        A filter clause for a source extension or query, as allowed by Malloy.

    Examples
    --------
    >>> import pymalloy as pm
    >>> clause = pm.where((pm.col("amount") > 0) & (pm.col("region") == "North"))
    >>> clause.text.startswith("where: ")
    True
    """
    return construct("where", "where: ", _scalar(predicate))


def having(predicate: Expr) -> Fragment:
    """Filter groups using aggregate output values.

    Parameters
    ----------
    predicate : Expr
        Symbolic boolean condition. Use where to filter input rows and having to filter grouped results. Reference a named aggregate with col.

    Returns
    -------
    Fragment
        A filter clause for a source extension or query, as allowed by Malloy.

    Examples
    --------
    >>> import pymalloy as pm
    >>> clause = pm.having(pm.col("revenue") > 100)
    >>> clause.text.startswith("having: ")
    True
    """
    return construct("having", "having: ", _scalar(predicate))


def order_by(*fields: Expr | Sort) -> Fragment:
    """Order query output using expressions and explicit sort directions.

    Parameters
    ----------
    *fields : Expr or Sort
        At least one expression or ``expr.asc()`` / ``expr.desc()`` value.
        A bare expression leaves direction to Malloy's defaults, which depend
        on whether the output is a dimension or measure. Use an explicit
        direction when ordering is part of the result contract.

    Returns
    -------
    Fragment
        An order_by clause. Include a tie-breaker for deterministic ranking.

    Examples
    --------
    >>> import pymalloy as pm
    >>> ordering = pm.order_by(pm.col("revenue").desc(), pm.col("region").asc())
    >>> ordering.text
    'order_by: revenue desc, region asc'
    """
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
    """Limit the number of rows in a query stage.

    Parameters
    ----------
    rows : int
        Nonnegative row count. Zero selects no output rows. Booleans are rejected.

    Returns
    -------
    Fragment
        A limit clause. Pair it with order_by for a defined top-N result.

    Notes
    -----
    This limits output, not necessarily input scanning or aggregation cost.
    Use ``Query.preview`` to bound an exploratory execution without editing
    an authored query.

    Examples
    --------
    >>> import pymalloy as pm
    >>> pm.limit(5).text
    'limit: 5'
    """
    if type(rows) is not int or rows < 0:
        raise ValueError("Limit must be a nonnegative integer")
    return construct("limit", f"limit: {rows}", arguments=(str(rows),))


def primary_key(field: str) -> Fragment:
    """Declare the field that identifies one source row.

    Parameters
    ----------
    field : str
        One field identifier, such as ``"order_id"``.

    Returns
    -------
    Fragment
        A primary_key clause for a source extension.

    Notes
    -----
    This is a semantic declaration, not a uniqueness constraint enforced on the
    input. Validate uniqueness and non-nullness before relying on the key for
    join and aggregate semantics.

    Examples
    --------
    >>> import pymalloy as pm
    >>> source = pm.table("orders.parquet").extend(pm.primary_key("order_id"))
    >>> source.text.splitlines()[1].strip()
    'primary_key: order_id'
    """
    return construct(
        "primary_key", "primary_key: ", identifier(field), arguments=(field,)
    )


def join(
    name: str, source: Fragment, *, on: Expr, kind: Literal["one", "many", "cross"]
) -> Fragment:
    """Attach a related source with an explicit relationship and condition.

    Parameters
    ----------
    name : str
        Joined source name used in field paths, for example ``"customer"``.
    source : Fragment
        Source expression or reference to an existing source.
    on : Expr
        Symbolic join condition. Qualify joined fields with separate ``col``
        path components, such as ``col("customer", "id")``.
    kind : {"one", "many", "cross"}
        Malloy relationship from the current source to the joined source.
        Required even when the relationship seems obvious. A cross join still
        requires an explicit condition, such as ``lit(True)``.

    Returns
    -------
    Fragment
        A join clause for a source extension.

    Notes
    -----
    Relationship declarations affect aggregate locality. They do not verify
    cardinality in your data. Test keys and join coverage separately.

    Examples
    --------
    >>> import pymalloy as pm
    >>> orders = pm.table("orders.parquet").extend(pm.join(
    ...     "customer", pm.ref("customers"), kind="one",
    ...     on=pm.col("customer_id") == pm.col("customer", "id"),
    ... ))
    >>> orders.names
    ('customer',)
    """
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
