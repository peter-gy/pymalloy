from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from pymalloy._snapshot import snapshot


@dataclass(frozen=True)
class Column:
    name: str
    type: str


@dataclass(frozen=True)
class Result:
    """A materialized query result. Conversion libraries are imported on demand."""

    sql: str
    columns: tuple[Column, ...]
    _values: tuple[tuple[Any, ...], ...] = field(repr=False)

    def rows(self) -> list[dict[str, Any]]:
        names = tuple(column.name for column in self.columns)
        return [dict(zip(names, row, strict=True)) for row in snapshot(self._values)]

    def arrow(self):
        import pyarrow as pa

        schema = _arrow_schema(self.columns)
        values = (
            zip(*self._values, strict=True)
            if self._values
            else (() for _ in self.columns)
        )
        return pa.Table.from_arrays(
            [
                pa.array(column, type=field.type)
                for column, field in zip(values, schema, strict=True)
            ],
            schema=schema,
        )

    def polars(self):
        import polars as pl

        return pl.from_arrow(self.arrow())


@lru_cache(maxsize=32)
def _arrow_schema(columns: tuple[Column, ...]):
    import duckdb
    import pyarrow as pa

    if not columns:
        return pa.schema([])
    select = ", ".join(
        f'CAST(NULL AS {column.type}) AS "{column.name.replace(chr(34), chr(34) * 2)}"'
        for column in columns
    )
    with duckdb.connect() as connection:
        return (
            connection.execute(f"SELECT {select} WHERE FALSE").to_arrow_table().schema
        )
