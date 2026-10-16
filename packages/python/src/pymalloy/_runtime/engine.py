from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from pymalloy._model.file_access import settings as connection_settings
from pymalloy._protocol.records import SchemaNeed, TableSchemaNeed
from pymalloy.errors import SchemaError
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
        self._pid = os.getpid()
        self._abandoned = False
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
        settings = connection_settings(data_root, config=config)
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
                self.connection.execute(
                    "SET VARIABLE data_root = ?",
                    [str(Path(settings.get("file_search_path", Path.cwd())).resolve())],
                )
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

    def describe(self, need: SchemaNeed) -> list[Column]:
        sql = "DESCRIBE " + (
            need.table_path if isinstance(need, TableSchemaNeed) else need.sql
        )
        try:
            statements = self.connection.extract_statements(sql)
            if len(statements) != 1:
                raise SchemaError("Schema discovery requires one statement", sql=sql)
            rows = self.connection.execute(statements[0]).fetchall()
        except duckdb.TransactionException as error:
            raise duckdb.TransactionException(
                f"Schema discovery failed: {error}. The connection owner must ROLLBACK the aborted transaction."
            ) from error
        except duckdb.Error as error:
            raise SchemaError(str(error), sql=sql) from error
        return [Column(name=row[0], type=row[1]) for row in rows]

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
        if self._pid != os.getpid():
            if not self._abandoned:
                from pymalloy._native import _abandon_inherited

                # DuckDB teardown can wait for parent threads that do not exist here.
                _abandon_inherited(self.connection, self._pid)
                self._abandoned = True
            return
        if self.owned:
            self.connection.close()
