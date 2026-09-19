import math
import time
from collections.abc import Mapping, Sequence
from contextlib import ExitStack, closing
from glob import has_magic
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import unquote, urlsplit

import duckdb

import pymalloy as pm
from pymalloy._headless.tooling import compiler_lease
from pymalloy._model.source import read_text
from pymalloy.analysis import MarkdownCell
from pymalloy.analysis import QueryCell as CompiledQueryCell
from pymalloy.export._document import (
    Document,
    Markdown,
    Profile,
    QueryCell,
    native_extensions,
    remote_urls,
)
from pymalloy.export._files import check_files, file_config
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

    def remaining() -> float:
        budget = deadline - time.monotonic()
        if budget <= 0:
            raise TimeoutError("Export compilation exceeded its deadline")
        return budget

    if profile == Profile.WIDGET and database is not None:
        raise ValueError(
            "MalloyWidget export requires files rather than a native database"
        )
    remote = set(remote_urls(remote_files))
    extensions = native_extensions(extensions, profile, remote)
    registered = dict(files)
    with ExitStack() as resources:
        parser = resources.enter_context(compiler_lease(deadline))
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
                    identifier = table.path
                    if identifier.startswith("'") and identifier.endswith("'"):
                        identifier = '"' + alias.replace('"', '""') + '"'
                    try:
                        catalog.execute(
                            "SELECT * FROM pragma_table_info(?)", [identifier]
                        )
                    except duckdb.CatalogException:
                        pass
                    else:
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
    if profile != Profile.WIDGET:
        check_files(registered)
    extensions = native_extensions(extensions, profile, remote)
    with closing(
        pm.model(
            path,
            data_root=data_root,
            connection_name=connection_name,
            config=file_config(registered, tuple(remote))
            if profile != Profile.WIDGET
            else None,
            extensions=extensions,
            database=database,
            read_only=database is not None,
            timeout=remaining(),
        )
    ) as model:
        selected = model.document(
            queries=queries, all=all, givens=givens, timeout=remaining()
        )
        captured = (
            model.source(timeout=remaining())
            if profile != Profile.PRECOMPILED
            else None
        )
        if profile == Profile.WIDGET:
            for alias, location in registered.items():
                if has_magic(alias) or not location.is_file():
                    raise ValueError(
                        f"MalloyWidget file {alias!r} must refer to a local file"
                    )
            # Validate unselected SQL cells too, so later widget selections remain executable.
            selected_names = {
                cell.name for cell in selected if isinstance(cell, CompiledQueryCell)
            }
            unselected_sql = [
                q.name
                for q in model.queries
                if q.kind == "sql" and q.name not in selected_names
            ]
            extra = (
                model.document(
                    queries=unselected_sql, givens=givens, timeout=remaining()
                )
                if unselected_sql
                else []
            )
        else:
            extra = []
        cells: list[Markdown | QueryCell] = []
        for cell in [*selected, *extra]:
            if isinstance(cell, MarkdownCell):
                cells.append(Markdown(cell.text))
            else:
                sql, kind, destination = export_sql(model.connection, cell.sql)
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
                cells.append(QueryCell(cell.name, sql, kind))
        remaining()
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
