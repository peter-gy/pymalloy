from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import polars as pl
    import pyarrow as pa


@dataclass(frozen=True)
class Column:
    """An output field name and its native DuckDB type text.

    Attributes
    ----------
    name : str
        Output column name.
    type : str
        Native type description. Use Result.arrow().schema for Arrow types.
    """

    name: str
    type: str


@dataclass(frozen=True)
class Result:
    """Materialized query data with SQL and native column descriptions.

    Returned by run, Query.run and Query.preview. It retains a DuckDB-produced
    Arrow table independently of compiler/connection lifetime.

    Attributes
    ----------
    sql : str
        SQL executed to produce this result, including a preview limit if applied.
    columns : tuple of Column
        Ordered native field names and type descriptions. COPY has no columns.

    See Also
    --------
    Result.rows, Result.arrow, Result.polars

    Examples
    --------
    >>> import pymalloy as pm
    >>> result = pm.run("run: duckdb.sql('SELECT 42 AS n') -> {select: n}")
    >>> result.columns[0].name
    'n'
    >>> result.rows()
    [{'n': 42}]
    """

    sql: str
    columns: tuple[Column, ...]
    _table: pa.Table = field(repr=False)

    def rows(self) -> list[dict[str, Any]]:
        """Materialize detached Python dictionaries in result order.

        Returns
        -------
        list of dict
            One dictionary per row using Arrow scalar representations. Decimal
            values remain Decimal, large integers remain exact, nested values remain
            nested, and nulls become None. Mutating these containers cannot change
            the retained result. Empty results return an empty list.

        Notes
        -----
        This conversion allocates Python objects. Prefer arrow or polars for large
        columnar results. Timestamp conversion uses the Arrow timezone metadata.

        Examples
        --------
        >>> import pymalloy as pm
        >>> result = pm.run("run: duckdb.sql('SELECT 9007199254740993::BIGINT AS id') -> {select: id}")
        >>> rows = result.rows()
        >>> rows[0]["id"] = 0
        >>> result.rows()
        [{'id': 9007199254740993}]
        """
        return self._table.to_pylist()

    def arrow(self) -> pa.Table:
        """Return the retained materialized PyArrow table.

        Returns
        -------
        pyarrow.Table
            The result's table without a conversion or buffer copy. Empty SELECTs
            retain their schema. Data remains usable after the model closes.

        Examples
        --------
        >>> import pymalloy as pm
        >>> result = pm.run("run: duckdb.sql('SELECT 42 AS n') -> {select: n}")
        >>> result.arrow().to_pylist()
        [{'n': 42}]
        """
        return self._table

    def polars(self) -> pl.DataFrame:
        """Convert the retained Arrow table to a Polars DataFrame.

        Returns
        -------
        polars.DataFrame
            A dataframe constructed without rechunking. Compatible Arrow buffers
            can be reused. Types requiring conversion may allocate new buffers.

        Notes
        -----
        Requires Polars, installed directly with ``pip install polars``. The headless extra
        alone supports rows and arrow but does not install Polars.

        Examples
        --------
        >>> import pymalloy as pm
        >>> result = pm.run("run: duckdb.sql('SELECT 42 AS n') -> {select: n}")
        >>> result.polars().to_dicts()
        [{'n': 42}]
        """
        import polars as pl

        return cast("pl.DataFrame", pl.from_arrow(self._table, rechunk=False))
