import math
import time
from collections.abc import Mapping, Sequence
from contextlib import closing
from glob import has_magic
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import pymalloy as pm
from pymalloy._document import Document, Markdown, Profile, Query
from pymalloy._server.compiler import Compiler
from pymalloy.analysis import MarkdownCell, QueryCell
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
    registered = dict(files)
    if profile == Profile.WIDGET:
        with closing(Compiler(timeout=remaining())) as parser:
            pending = [path.resolve()]
            visited = set()
            while pending:
                source_path = pending.pop()
                if source_path in visited:
                    continue
                visited.add(source_path)
                parsed = parser.parse(
                    source_path.read_text(), url=source_path.as_uri(), deadline=deadline
                )
                for table in parsed.tables:
                    alias = table.path
                    scheme = urlsplit(alias).scheme
                    if scheme in {"http", "https"}:
                        continue
                    if (
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
                        raise ValueError(
                            f"MalloyWidget file {alias!r} is missing. Declare SQL reader files with files=."
                        )
                    registered[alias] = location.resolve()
                for imported in parsed.imports:
                    target = urlsplit(imported.url)
                    if target.scheme != "file":
                        raise ValueError(
                            "MalloyWidget export source imports must be local files"
                        )
                    pending.append(Path(unquote(target.path)))
    with closing(
        pm.model(
            path,
            data_root=data_root,
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
                cell.name for cell in selected if isinstance(cell, QueryCell)
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
        cells = []
        for cell in [*selected, *extra]:
            if isinstance(cell, MarkdownCell):
                cells.append(Markdown(cell.text))
            else:
                sql, kind = export_sql(model.connection, cell.sql)
                if profile == Profile.WIDGET and kind == "copy":
                    raise ValueError(
                        "MalloyWidget export cannot execute COPY statements"
                    )
                cells.append(Query(cell.name, sql, kind))
        remaining()
        return Document(
            title=title,
            cells=tuple(cells[: len(selected)]),
            data_root=data_root,
            database=database,
            source=captured,
            profile=profile,
            givens=dict(givens or {}),
            files=registered,
        )
