from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from pymalloy._model.errors import SchemaError
from pymalloy._protocol.records import SchemaNeed, TableSchemaNeed
from pymalloy.result import Column, Result

from .deadline import interrupt_at


class Engine:
    def __init__(
        self,
        *,
        data_root: str | Path | None = None,
        database: str | Path | None = None,
        connection: duckdb.DuckDBPyConnection | None = None,
        config: Mapping[str, Any] | None = None,
        extensions: Sequence[str] = (),
        read_only: bool = False,
        deadline: float | None = None,
    ) -> None:
        if isinstance(extensions, (str, bytes)) or not all(
            isinstance(name, str) for name in extensions
        ):
            raise TypeError("extensions must be a sequence of extension names")
        if connection is not None and (
            data_root is not None
            or database is not None
            or config is not None
            or extensions
            or read_only
        ):
            raise ValueError(
                "Borrowed connections use the caller's database, configuration, and file_search_path"
            )
        self.owned = connection is None
        if connection is not None:
            self.connection = connection
            return
        settings = {name.lower(): value for name, value in (config or {}).items()}
        if data_root is not None and "file_search_path" in settings:
            raise ValueError("Choose data_root or config['file_search_path']")
        if "file_search_path" not in settings:
            root = Path(data_root or Path.cwd()).resolve()
            if not root.is_dir():
                raise ValueError(f"Data directory does not exist: {root}")
            settings["file_search_path"] = str(root)
        settings.setdefault("timezone", "UTC")
        # Timezone requires ICU, and allowlists require a started database. Lock last.
        deferred = {
            name: settings.pop(name)
            for name in (
                "timezone",
                "allowed_paths",
                "allowed_directories",
                "enable_external_access",
                "lock_configuration",
            )
            if name in settings
        }
        self.connection = duckdb.connect(
            str(database) if database is not None else ":memory:",
            read_only=read_only,
            config=settings,
        )
        try:
            with interrupt_at(
                self.connection, deadline, message="Model startup exceeded its deadline"
            ):
                for extension in extensions:
                    self.connection.install_extension(extension)
                    self.connection.load_extension(extension)
                if extensions:
                    # Persistent credentials are initialized before external access is restricted.
                    self.connection.execute("SELECT count(*) FROM duckdb_secrets()")
                for name, value in deferred.items():
                    self.connection.execute(f"SET {name} = ?", [value])
        except BaseException:
            self.connection.close()
            raise

    def describe(self, need: SchemaNeed) -> list[dict[str, str]]:
        sql = "DESCRIBE " + (
            need.table_path if isinstance(need, TableSchemaNeed) else need.sql
        )
        try:
            rows = self.connection.execute(sql).fetchall()
        except duckdb.Error as error:
            raise SchemaError(str(error), sql=sql) from error
        return [{"name": row[0], "type": row[1]} for row in rows]

    def run(self, sql: str) -> Result:
        statements = self.connection.extract_statements(sql)
        if len(statements) != 1 or statements[0].type not in {
            duckdb.StatementType.SELECT,
            duckdb.StatementType.COPY,
        }:
            raise ValueError("Query execution requires one SELECT or COPY statement")
        self.connection.execute(statements[0])
        if statements[0].type == duckdb.StatementType.COPY:
            return Result(sql, (), pa.table({}))
        return self._result(sql, self.connection)

    @staticmethod
    def _result(
        sql: str, native: duckdb.DuckDBPyConnection | duckdb.DuckDBPyRelation
    ) -> Result:
        columns = tuple(
            Column(name=item[0], type=str(item[1])) for item in native.description
        )
        return Result(sql, columns, native.to_arrow_table())

    def preview(self, sql: str, limit: int) -> Result:
        statements = self.connection.extract_statements(sql)
        if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
            raise ValueError("Preview requires one SELECT statement")
        relation = self.connection.sql(statements[0])
        assert relation is not None
        limited = relation.limit(limit)
        return self._result(limited.sql_query(), limited)

    def close(self) -> None:
        if self.owned:
            self.connection.close()
