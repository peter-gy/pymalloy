from collections.abc import Callable
from pathlib import Path

import duckdb

from pymalloy.server._sql import Statement, bind_statement


class DataAccess:
    """Resolve SQL identifiers and file paths against one borrowed connection."""

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self.connection = connection
        self.on_file: Callable[[str, str], None] | None = None

    def _table_exists(self, path: str) -> bool:
        try:
            self.connection.execute(
                "SELECT 1 FROM pragma_table_info(?::VARCHAR) LIMIT 0", [path]
            )
        except (duckdb.CatalogException, duckdb.BinderException) as error:
            message = str(error).split("\n", 1)[0]
            if (
                message.startswith(
                    (
                        "Catalog Error: Table with name ",
                        "Catalog Error: Schema with name ",
                        "Catalog Error: Catalog with name ",
                        "Binder Error: Catalog ",
                    )
                )
                and " does not exist" in message
            ):
                return False
            raise
        return True

    def bind(
        self, sql: str, *, data_root: Path | None = None, allow_write: bool = False
    ) -> Statement:
        return bind_statement(
            sql,
            table_exists=self._table_exists,
            data_root=data_root,
            allow_write=allow_write,
            on_file=self.on_file,
        )

    def describe(self, sql: str, data_root: Path) -> list[dict[str, str]]:
        statement = self.bind(sql, data_root=data_root)
        rows = self.connection.execute("DESCRIBE " + statement.sql).fetchall()
        return [{"name": row[0], "type": row[1]} for row in rows]
