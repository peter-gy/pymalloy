from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import polars as pl
    import pyarrow as pa


@dataclass(frozen=True)
class Column:
    name: str
    type: str


@dataclass(frozen=True)
class Result:
    """An Arrow-backed query result that remains usable after its model closes."""

    sql: str
    columns: tuple[Column, ...]
    _table: pa.Table = field(repr=False)

    def rows(self) -> list[dict[str, Any]]:
        """Materialize detached Python rows using Arrow's scalar representations."""
        return self._table.to_pylist()

    def arrow(self) -> pa.Table:
        """Return the materialized Arrow table without copying its buffers."""
        return self._table

    def polars(self) -> pl.DataFrame:
        """View the Arrow result as a dataframe without consolidating its chunks."""
        import polars as pl

        return cast("pl.DataFrame", pl.from_arrow(self._table, rechunk=False))
