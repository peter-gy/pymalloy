import json
from collections.abc import Mapping, Sequence
from glob import has_magic
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pymalloy._document import Document, Markdown, Query
from pymalloy._source import ModelSource
from pymalloy.server._givens import encode_givens, given_values
from pymalloy.server._runtime import NativeRuntime


def compile_document(
    path: Path,
    *,
    queries: Sequence[str],
    givens: Mapping[str, Any] | None,
    data_root: Path,
    database: Path | None,
    timeout: float,
    profile: Literal["precompiled", "native", "widget"],
    title: str,
) -> Document:
    """Compile ordered cells using the native schema and data-binding contract."""
    if profile == "widget" and database is not None:
        raise ValueError(
            "Widget export cannot use a native DuckDB database; "
            "use profile='native' or supply data files"
        )
    files: dict[str, str] = {}

    def capture_file(alias: str, location: str) -> None:
        url = urlsplit(location)
        if url.scheme and url.scheme not in {"http", "https"}:
            raise ValueError(
                f"Widget export cannot read {alias!r}; use a local path or HTTP(S) URL"
            )
        if has_magic(url.path if url.scheme else location):
            raise ValueError(
                f"Widget export cannot register file glob {alias!r}; "
                "list the files explicitly"
            )
        if url.scheme:
            return
        if "#" in alias or "\x00" in alias or alias.startswith("//"):
            raise ValueError(
                f"Widget export cannot register file name {alias!r}; "
                "rename the file or use profile='native'"
            )
        files[alias] = str(Path(location).resolve())

    values = encode_givens(givens)
    with (
        NativeRuntime(
            data_root=data_root,
            database=database,
            read_only=database is not None,
            timeout=timeout,
        ) as runtime,
        runtime._operation(),
    ):
        if profile == "widget":
            runtime._data.on_file = capture_file
        loaded = runtime._request({"op": "load", "url": path.as_uri()}, data_root)
        response = runtime._request(
            {
                "op": "document",
                "model": loaded["model"],
                "queries": list(queries),
                "givens": values,
                "profile": "native" if profile == "widget" else profile,
            },
            data_root,
        )
        cells: list[Markdown | Query] = []
        selected = response["cells"]
        extra = []
        if profile == "widget":
            names = {cell["name"] for cell in selected if cell["kind"] == "query"}
            remaining_sql = [
                name
                for name in loaded["queries"]
                if name.startswith("sql:") and name not in names
            ]
            if remaining_sql:
                extra = runtime._request(
                    {
                        "op": "document",
                        "model": loaded["model"],
                        "queries": remaining_sql,
                        "givens": values,
                        "profile": "precompiled",
                    },
                    data_root,
                )["cells"]
        for cell in [*selected, *extra]:
            if cell["kind"] == "markdown":
                cells.append(Markdown(cell["text"]))
            else:
                statement = runtime._data.bind(
                    cell["sql"],
                    allow_write=True,
                    data_root=data_root if profile == "widget" else None,
                )
                if profile == "widget" and statement.kind == "copy":
                    raise ValueError(
                        "Widget export cannot execute COPY statements; "
                        "use profile='native' or profile='precompiled'"
                    )
                cells.append(Query(cell["name"], statement.sql, statement.kind))
        source = (
            ModelSource(**response["source"])
            if profile in {"native", "widget"}
            else None
        )
        return Document(
            title=title,
            cells=tuple(cells[: len(selected)]),
            data_root=data_root,
            database=database,
            source=source,
            profile=profile,
            _widget_files=tuple(sorted(files.items())),
            _givens_json=json.dumps(
                given_values(values), sort_keys=True, ensure_ascii=False
            )
            if source is not None
            else "{}",
        )
