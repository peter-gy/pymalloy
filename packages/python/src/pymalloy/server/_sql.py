from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal
from urllib.parse import urlsplit

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope

_IDENTIFIER_CASE = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"
)

FILE_SUFFIXES = {".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".parquet"}
FILE_READERS = {
    "read_csv",
    "read_csv_auto",
    "read_json",
    "read_json_auto",
    "read_ndjson",
    "read_ndjson_auto",
    "read_json_objects",
    "read_json_objects_auto",
    "read_ndjson_objects",
    "read_parquet",
    "parquet_scan",
    "read_text",
    "read_blob",
}


def _file_path(value: str) -> bool:
    url = urlsplit(value)
    return any(
        suffix.lower() in FILE_SUFFIXES
        for suffix in PurePosixPath(url.path if url.scheme else value).suffixes
    )


def _rooted_path(
    expression: exp.Expr,
    data_root: Path | None = None,
    on_file: Callable[[str, str], None] | None = None,
) -> exp.Expr:
    if isinstance(expression, exp.Array):
        return exp.Array(
            expressions=[
                _rooted_path(item, data_root, on_file)
                for item in expression.expressions
            ]
        )
    if not isinstance(expression, exp.Literal) or not expression.is_string:
        raise ValueError("File readers require a literal path or list of literal paths")
    value = expression.this
    if (
        urlsplit(value).scheme
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
    ):
        if on_file is not None:
            on_file(value, value)
        return expression
    if on_file is not None:
        on_file(value, ((data_root or Path.cwd()) / value).as_posix())
    if data_root is not None:
        return exp.Literal.string((data_root / value).as_posix())
    return exp.DPipe(
        this=exp.Anonymous(
            this="getvariable", expressions=[exp.Literal.string("data_root")]
        ),
        expression=exp.Literal.string("/" + value),
    )


@dataclass(frozen=True)
class Statement:
    sql: str
    kind: Literal["select", "copy"]


def _visible_cte_names(scope: Scope) -> set[str]:
    ancestors = set()
    expression = scope.expression
    while expression is not None:
        ancestors.add(id(expression))
        expression = expression.parent
    visible = set()
    for name in scope.cte_sources:
        folded = name.translate(_IDENTIFIER_CASE)
        owner = scope
        while owner is not None:
            # SQLGlot gives recursive seeds their own binding. DuckDB resolves
            # that term before self-reference, allowing an outer CTE or file.
            if any(
                alias.translate(_IDENTIFIER_CASE) == folded
                and id(source.expression) not in ancestors
                for alias, source in owner.cte_sources.items()
            ):
                visible.add(folded)
                break
            owner = owner.parent
    return visible


def bind_statement(
    sql: str,
    *,
    table_exists: Callable[[str], bool],
    allow_write: bool = False,
    data_root: Path | None = None,
    on_file: Callable[[str, str], None] | None = None,
) -> Statement:
    """Classify one statement and bind its relative file references."""
    exists = cache(table_exists)
    statements = sqlglot.parse(sql, read="duckdb")
    if len(statements) != 1 or not isinstance(
        statements[0], (exp.Query, exp.Copy) if allow_write else exp.Query
    ):
        raise ValueError(
            "Data sources and compiled queries must contain one SELECT statement"
        )
    tree = statements[0]
    # SQLGlot stores a lateral alias outside UNNEST, but its DuckDB generator
    # restores the ordinality column only when UNNEST owns that alias.
    for lateral in tree.find_all(exp.Lateral):
        if isinstance(lateral.this, exp.Unnest) and lateral.args.get("alias"):
            lateral.this.set("alias", lateral.args["alias"])
            lateral.set("alias", None)
    if isinstance(tree, exp.Copy):
        tree.set(
            "files",
            [
                exp.Paren(this=_rooted_path(path, data_root))
                for path in tree.args["files"]
            ],
        )
    cte_tables = set()
    for scope in traverse_scope(tree):
        # DuckDB folds ASCII identifier case, including quoted identifiers.
        names = _visible_cte_names(scope)
        cte_tables.update(
            id(table)
            for table in scope.tables
            if not table.db
            and not table.catalog
            and table.name.translate(_IDENTIFIER_CASE) in names
        )
    for table in list(tree.find_all(exp.Table)):
        if isinstance(table.this, exp.Identifier):
            parts = tuple(part.name for part in table.parts)
            path = ".".join(parts)
            identifier = ".".join(
                part.sql(dialect="duckdb", identify=True) for part in table.parts
            )
            if (
                id(table) not in cte_tables
                and _file_path(path)
                and not exists(identifier)
            ):
                file = PurePosixPath(path)
                if file.suffix.lower() in {".gz", ".zst", ".zstd"}:
                    file = file.with_suffix("")
                alias = table.args.get("alias") or exp.TableAlias(
                    this=exp.to_identifier(file.stem)
                )
                table.replace(
                    exp.Table(
                        this=exp.Anonymous(
                            this="query_table",
                            expressions=[
                                _rooted_path(
                                    exp.Literal.string(path), data_root, on_file
                                )
                            ],
                        ),
                        alias=alias,
                    )
                )
        elif isinstance(table.this, exp.Func):
            function = table.this
            name = (
                function.name.lower()
                if isinstance(function, exp.Anonymous)
                else function.sql_name().lower()
            )
            if name == "query_table" and function.expressions:
                argument = function.expressions[0]
                paths = (
                    argument.expressions
                    if isinstance(argument, exp.Array)
                    else [argument]
                )
                for path in paths:
                    if on_file is not None and (
                        not isinstance(path, exp.Literal) or not path.is_string
                    ):
                        raise ValueError(
                            "Widget export requires literal query_table paths"
                        )
                    if (
                        isinstance(path, exp.Literal)
                        and path.is_string
                        and _file_path(path.this)
                        and not exists(path.this)
                    ):
                        path.replace(_rooted_path(path, data_root, on_file))
            elif name in FILE_READERS:
                if isinstance(function, exp.ReadCSV):
                    function.set(
                        "this", _rooted_path(function.this, data_root, on_file)
                    )
                else:
                    function.set(
                        "expressions",
                        [
                            _rooted_path(function.expressions[0], data_root, on_file),
                            *function.expressions[1:],
                        ],
                    )
    return Statement(
        sql=tree.sql(
            dialect="duckdb", pretty=True, unsupported_level=sqlglot.ErrorLevel.RAISE
        ),
        kind="copy" if isinstance(tree, exp.Copy) else "select",
    )
