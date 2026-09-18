"""Materialize closed source graphs using compiler-selected import and table spans."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
import time
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from pymalloy._errors import CompilationError
from pymalloy._givens import encode_givens, given_values
from pymalloy._records import FormatReady, SourceRange
from pymalloy._source import ModelSource
from pymalloy.authoring import _table_path, table


@dataclass(frozen=True)
class SourceBundle:
    """Ordinary model files, their data search directory, and a replay manifest."""

    model: Path
    data_root: Path
    manifest: Path


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _offsets(source: str, span: SourceRange) -> tuple[int, int]:
    lines = source.splitlines(keepends=True)
    return (
        sum(len(line) for line in lines[: span.start.line]) + span.start.character,
        sum(len(line) for line in lines[: span.end.line]) + span.end.character,
    )


def bundle(
    source: ModelSource,
    directory: str | Path,
    *,
    files: Mapping[str | Path, str | Path] | None = None,
    query: str | None = None,
    givens: Mapping[str, Any] | None = None,
    format: bool = True,
    timeout: float = 120,
) -> SourceBundle:
    """Write a closed Malloy source graph and explicit file bindings to a new directory.

    Binding keys match table paths (use a Path key for a table created from a Path).
    Relative string keys also expose files to SQL readers through file_search_path.
    SQL text and database identifiers without explicit bindings remain unchanged.
    The manifest records parameters, source identities and copied input hashes.
    """
    from pymalloy._server.compiler import Compiler

    if not isinstance(source, ModelSource):
        raise TypeError("bundle requires a closed ModelSource snapshot")
    if type(format) is not bool:
        raise TypeError("format must be a boolean")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Bundle timeout must be finite and positive")
    if query is not None and (not isinstance(query, str) or not query):
        raise ValueError("query must be a nonempty name")
    parameters = given_values(encode_givens(givens))
    target = Path(directory).absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    if not target.parent.is_dir():
        raise FileNotFoundError(target.parent)
    if any(
        urlsplit(url).path.endswith((".malloynb", ".malloysql"))
        for url in [source.url, *source.imports]
    ):
        raise ValueError("Source bundles require plain .malloy documents")

    # Import identity is distinct from the inline root, even when their URLs coincide.
    destinations = {
        url: PurePosixPath("sources")
        / (hashlib.sha256(url.encode()).hexdigest() + ".malloy")
        for url in source.imports
    }
    inputs = []
    bindings: dict[str, str] = {}
    aliases = set()
    for key, value in (files or {}).items():
        if not isinstance(key, (str, Path)) or not str(key):
            raise TypeError("File bindings require string or Path keys")
        path = Path(value).resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"File binding is not a regular file: {path}")
        # Reuse the authoring API's distinction between file Paths and catalog strings.
        reference = _table_path(key)
        alias = PurePosixPath(str(key))
        if (
            not isinstance(key, str)
            or alias.is_absolute()
            or ".." in alias.parts
            or "\\" in str(key)
            or ":" in str(key)
            or (str(key).startswith("'") and str(key).endswith("'"))
        ):
            alias = PurePosixPath("__files__") / (
                hashlib.sha256(reference.encode()).hexdigest() + path.suffix
            )
        if str(alias) in {"", "."} or str(alias).casefold() in aliases:
            raise ValueError(f"File bindings have a colliding destination: {key}")
        aliases.add(str(alias).casefold())
        if reference in bindings:
            raise ValueError(f"Duplicate table binding: {reference}")
        bindings[reference] = str(alias)
        inputs.append((path, alias, reference))
    inputs.sort(key=lambda entry: entry[2])

    deadline = time.monotonic() + timeout
    documents = []
    originals = [(source.url, source.text, PurePosixPath("model.malloy"))]
    originals.extend(
        (url, text, destinations[url]) for url, text in sorted(source.imports.items())
    )
    with closing(Compiler(timeout=timeout)) as compiler:
        for url, original, destination in originals:
            if time.monotonic() >= deadline:
                raise TimeoutError("Source bundle deadline exceeded")
            text = original
            if format:
                formatted = compiler.request(
                    {"op": "format", "source": text},
                    FormatReady,
                    describe=lambda sql: [],
                    deadline=deadline,
                )
                if formatted.diagnostics:
                    raise CompilationError(
                        "Cannot format source bundle", diagnostics=formatted.diagnostics
                    )
                text = formatted.source
            parsed = compiler.parse(text, url=url, deadline=deadline)
            if any(d.severity == "error" for d in parsed.diagnostics):
                raise CompilationError(
                    "Cannot parse source bundle", diagnostics=parsed.diagnostics
                )
            edits = []
            for imported in parsed.imports:
                if imported.url not in destinations:
                    raise ValueError(f"Source bundle is missing {imported.url!r}")
                relative = os.path.relpath(
                    destinations[imported.url], destination.parent
                ).replace(os.sep, "/")
                edits.append(
                    (
                        imported.reference.start,
                        imported.reference.end,
                        json.dumps(relative),
                    )
                )
            for reference in parsed.tables:
                if reference.connection == "duckdb" and reference.path in bindings:
                    start, end = _offsets(text, reference.range)
                    edits.append(
                        (start, end, table(Path(bindings[reference.path])).text)
                    )
            last = len(text)
            for start, end, replacement in sorted(edits, reverse=True):
                if end > last or start < 0 or end < start:
                    raise ValueError(
                        "Compiler source references overlap or are out of range"
                    )
                text = text[:start] + replacement + text[end:]
                last = start
            documents.append((url, original, destination, text))

    with tempfile.TemporaryDirectory(prefix=".pymalloy-", dir=target.parent) as staging:
        staged = Path(staging) / "bundle"
        staged.mkdir()
        (staged / "data").mkdir()
        model_records = []
        for url, original, destination, text in documents:
            output = staged / destination
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(text.encode())
            model_records.append(
                {
                    "url": url,
                    "path": str(destination),
                    "sha256": _hash(output),
                    "original_sha256": hashlib.sha256(original.encode()).hexdigest(),
                }
            )
        file_records = []
        for path, alias, reference in inputs:
            output = staged / "data" / alias
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, output)
            file_records.append(
                {
                    "reference": reference,
                    "path": str(PurePosixPath("data") / alias),
                    "sha256": _hash(output),
                }
            )
        manifest = {
            "format_version": 1,
            "compiler_version": parsed.compiler_version,
            "model": "model.malloy",
            "data_root": "data",
            "query": query,
            "givens": parameters,
            "sources": model_records,
            "files": file_records,
        }
        (staged / "bundle.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        )
        if time.monotonic() >= deadline:
            raise TimeoutError("Source bundle deadline exceeded")
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        staged.rename(target)
    return SourceBundle(
        target / "model.malloy", target / "data", target / "bundle.json"
    )
