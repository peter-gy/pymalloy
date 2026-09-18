from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal
from urllib.parse import urlsplit

import duckdb


def export_sql(
    connection: duckdb.DuckDBPyConnection, sql: str
) -> tuple[str, Literal["select", "copy"], str | None]:
    """Validate an export statement and anchor relative COPY destinations."""
    statements = connection.extract_statements(sql)
    if len(statements) != 1:
        raise ValueError("SQL cells require one SELECT or COPY statement")
    kind = statements[0].type
    if kind == duckdb.StatementType.SELECT:
        return sql, "select", None
    if kind != duckdb.StatementType.COPY:
        raise ValueError("SQL cells require one SELECT or COPY statement")
    tokens = duckdb.tokenize(sql)
    positions = [position for position, _ in tokens] + [len(sql)]
    if len(tokens) < 3 or sql[positions[1]] != "(":
        raise ValueError("COPY requires a parenthesized SELECT and literal destination")
    depth = 1
    for index in range(2, len(tokens)):
        if sql[positions[index]] == "(":
            depth += 1
        elif sql[positions[index]] == ")":
            depth -= 1
        if depth:
            continue
        if (
            index + 2 >= len(tokens)
            or sql[positions[index + 1] : positions[index + 1] + 2].upper() != "TO"
            or tokens[index + 2][1] != duckdb.token_type.string_const
        ):
            raise ValueError(
                "COPY requires a parenthesized SELECT and literal destination"
            )
        start = positions[index + 2]
        end = positions[index + 3]
        # DuckDB parses string escapes and dollar quoting. Trailing comments are part of this span.
        row = connection.execute("SELECT " + sql[start:end]).fetchone()
        assert row is not None
        path = row[0]
        if (
            not urlsplit(path).scheme
            and not PurePosixPath(path).is_absolute()
            and not PureWindowsPath(path).is_absolute()
        ):
            literal = ("/" + path).replace("'", "''")
            sql = (
                sql[:start] + f"(getvariable('data_root') || '{literal}') " + sql[end:]
            )
        return sql, "copy", path
    raise ValueError("COPY requires a parenthesized SELECT and literal destination")
