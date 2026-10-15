import math
import re
import time
from collections.abc import Mapping, Sequence
from contextlib import ExitStack, closing
from glob import has_magic
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import unquote, urlsplit

import duckdb

import pymalloy as pm
from pymalloy._headless.compiler import Compiler
from pymalloy._headless.runtime import remaining
from pymalloy._model.file_access import check_files, settings
from pymalloy._model.source import read_text
from pymalloy.analysis import QueryCell as CompiledNotebookQuery
from pymalloy.export._document import (
    Document,
    MarkdownCell,
    NotebookQuery,
    Profile,
    native_extensions,
    remote_urls,
)
from pymalloy.export._sql import export_sql


def compile_document(
    path: Path,
    *,
    queries: Sequence[str] | None,
    all: bool,
    givens: Mapping[str, Any] | None,
    data_root: Path,
    database: Path | None,
    timeout: float,
    profile: Profile,
    connection_name: str,
    remote_files: Sequence[str],
    extensions: Sequence[str],
    title: str,
    files: Mapping[str, Path],
) -> Document:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Export timeout must be finite and positive")
    deadline = time.monotonic() + timeout

    if profile == Profile.WIDGET and database is not None:
        raise ValueError(
            "MalloyWidget export requires files rather than a native database"
        )
    remote = set(remote_urls(remote_files))
    extensions = native_extensions(extensions, profile, remote)
    registered = dict(files)
    with ExitStack() as resources:
        parser = resources.enter_context(closing(Compiler(timeout=remaining(deadline))))
        catalog = None
        pending = [path.resolve()]
        visited = set()
        while pending:
            source_path = pending.pop()
            if source_path in visited:
                continue
            visited.add(source_path)
            parsed = parser.parse(
                read_text(source_path),
                url=source_path.as_uri(),
                deadline=deadline,
                document_kind=None if source_path == path else "model",
            )
            for table in parsed.tables:
                alias = table.path
                if alias.startswith("'") and alias.endswith("'"):
                    alias = alias[1:-1].replace("''", "'")
                scheme = urlsplit(alias).scheme
                if scheme in {"http", "https"}:
                    remote.add(alias)
                    continue
                if profile == Profile.WIDGET and (
                    scheme
                    or has_magic(alias)
                    or "#" in alias
                    or "\x00" in alias
                    or alias.startswith("//")
                ):
                    raise ValueError(
                        f"MalloyWidget export requires an explicit local file or HTTP(S) URL: {alias!r}"
                    )
                location = registered.get(alias, data_root / alias)
                if not location.is_file():
                    if profile != Profile.WIDGET:
                        continue
                    raise ValueError(
                        f"MalloyWidget file {alias!r} is missing. Declare SQL reader files with files=."
                    )
                if database is not None and alias not in files:
                    if catalog is None:
                        catalog = resources.enter_context(
                            duckdb.connect(str(database), read_only=True)
                        )
                    # Malloy preserves identifier paths and quotes convenience file paths.
                    segment = r'(?:[A-Za-z_][A-Za-z_0-9]*|"(?:[^"]|"")*")'
                    spelling = table.path
                    if not spelling.startswith("'") and not re.fullmatch(
                        segment + r"(?:\." + segment + r")*", spelling
                    ):
                        spelling = "'" + spelling.replace("'", "''") + "'"
                    try:
                        identifiers = catalog.get_table_names(
                            "SELECT * FROM " + spelling, qualified=True
                        )
                    except duckdb.ParserException:
                        identifiers = set()
                    found = False
                    for identifier in identifiers:
                        try:
                            catalog.execute(
                                "SELECT * FROM pragma_table_info(?)", [identifier]
                            )
                        except (duckdb.CatalogException, duckdb.ParserException):
                            continue
                        found = True
                        break
                    if found:
                        continue
                registered[alias] = location.resolve()
            for imported in parsed.imports:
                target = urlsplit(imported.url)
                if target.scheme != "file":
                    if profile != Profile.WIDGET:
                        continue
                    raise ValueError(
                        "MalloyWidget export source imports must be local files"
                    )
                pending.append(Path(unquote(target.path)))
        if catalog is not None:
            catalog.close()
        if profile != Profile.WIDGET:
            check_files(registered)
        extensions = native_extensions(extensions, profile, remote)
        with pm.Connection._open(
            data_root=data_root if profile == Profile.WIDGET else None,
            name=connection_name,
            config=settings(data_root, registered, tuple(remote))
            if profile != Profile.WIDGET
            else None,
            extensions=extensions,
            database=database if database is not None else ":memory:",
            read_only=database is not None,
            timeout=remaining(deadline),
            deadline=deadline,
        ) as connection:
            model = connection._model(path, compiler=parser, deadline=deadline)
            selected = model._document(
                queries=queries, all=all, givens=givens, deadline=deadline
            )
            captured = model.source() if profile != Profile.PRECOMPILED else None
            if profile == Profile.WIDGET:
                for alias, location in registered.items():
                    if has_magic(alias) or not location.is_file():
                        raise ValueError(
                            f"MalloyWidget file {alias!r} must refer to a local file"
                        )
                # Validate unselected SQL cells too, so later widget selections remain executable.
                selected_names = {
                    cell.name
                    for cell in selected
                    if isinstance(cell, CompiledNotebookQuery)
                }
                unselected_sql = [
                    q.name
                    for q in model.queries
                    if q.kind == "sql" and q.name not in selected_names
                ]
                extra = (
                    model._document(
                        queries=unselected_sql, givens=givens, deadline=deadline
                    )
                    if unselected_sql
                    else []
                )
            else:
                extra = []
            cells: list[MarkdownCell | NotebookQuery] = []
            for cell in [*selected, *extra]:
                if isinstance(cell, MarkdownCell):
                    cells.append(cell)
                else:
                    sql, kind, destination = export_sql(connection.duckdb, cell.sql)
                    if destination is not None:
                        if (
                            urlsplit(destination).scheme
                            and not PureWindowsPath(destination).is_absolute()
                        ):
                            raise ValueError(
                                "Native notebook COPY destinations must be local files"
                            )
                        registered[destination] = (data_root / destination).resolve()
                    if profile == Profile.WIDGET and kind == "copy":
                        raise ValueError(
                            "MalloyWidget export cannot execute COPY statements"
                        )
                    cells.append(NotebookQuery(cell.name, sql, kind))
            remaining(deadline)
            return Document(
                title=title,
                cells=tuple(cells[: len(selected)]),
                data_root=data_root,
                connection_name=connection_name,
                remote_files=tuple(sorted(remote)),
                extensions=tuple(extensions),
                database=database,
                source=captured,
                profile=profile,
                givens=dict(givens or {}),
                files=registered,
            )
