from __future__ import annotations

from pathlib import Path

import duckdb

from pymalloy._errors import SchemaError
from pymalloy.result import Column, Result


class Engine:
    def __init__(
        self,
        *,
        data_root: str | Path | None = None,
        database: str | Path | None = None,
        connection: duckdb.DuckDBPyConnection | None = None,
        read_only: bool = False,
    ) -> None:
        if connection is not None and (
            data_root is not None or database is not None or read_only
        ):
            raise ValueError(
                "Borrowed connections use the caller's database and file_search_path"
            )
        self.owned = connection is None
        self.connection = (
            connection
            if connection is not None
            else duckdb.connect(
                str(database) if database is not None else ":memory:",
                read_only=read_only,
            )
        )
        if self.owned:
            try:
                root = Path(data_root or Path.cwd()).resolve()
                if not root.is_dir():
                    raise ValueError(f"Data directory does not exist: {root}")
                self.connection.execute("SET TimeZone='UTC'")
                self.connection.execute("SET file_search_path = ?", [str(root)])
            except BaseException:
                self.connection.close()
                raise

    def describe(self, sql: str) -> list[dict[str, str]]:
        try:
            rows = self.connection.execute("DESCRIBE " + sql).fetchall()
        except duckdb.Error as error:
            raise SchemaError(str(error)) from error
        return [{"name": row[0], "type": row[1]} for row in rows]

    def run(self, sql: str) -> Result:
        statements = self.connection.extract_statements(sql)
        if len(statements) != 1 or statements[0].type not in {
            duckdb.StatementType.SELECT,
            duckdb.StatementType.COPY,
        }:
            raise ValueError("Query execution requires one SELECT or COPY statement")
        self.connection.execute(sql)
        if statements[0].type == duckdb.StatementType.COPY:
            return Result(sql, (), ())
        columns = tuple(
            Column(name=item[0], type=str(item[1]))
            for item in self.connection.description
        )
        rows = tuple(self.connection.fetchall())
        return Result(sql, columns, rows)

    def preview(self, sql: str, limit: int) -> Result:
        statements = self.connection.extract_statements(sql)
        if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
            raise ValueError("Preview requires one SELECT statement")
        relation = self.connection.sql(sql)
        assert relation is not None
        return self.run(relation.limit(limit).sql_query())

    def close(self) -> None:
        if self.owned:
            self.connection.close()
