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
from itertools import accumulate
from pathlib import Path, PurePosixPath
from typing import Any

from pymalloy._authoring.draft import Draft
from pymalloy._authoring.syntax import Fragment, from_wire
from pymalloy._authoring.tables import table_path
from pymalloy._model import DEFAULT_CONNECTION
from pymalloy._model.errors import CompilationError
from pymalloy._model.source import ModelSource
from pymalloy._protocol.givens import encode_givens, given_values
from pymalloy._protocol.records import (
    FormatReady,
    FormatRequest,
    SyntaxReady,
    SyntaxRequest,
)
from pymalloy.authoring import table
from pymalloy.export._python import file_guard
from pymalloy.validation import Validation


@dataclass(frozen=True)
class SourceBundle:
    """Ordinary model files, their data search directory, and a replay manifest."""

    model: Path
    data_root: Path
    manifest: Path


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def bundle(
    source: ModelSource | Validation,
    directory: str | Path,
    *,
    files: Mapping[str | Path, str | Path] | None = None,
    query: str | None = None,
    connection_name: str | None = None,
    givens: Mapping[str, Any] | None = None,
    format: bool = True,
    timeout: float = 120,
) -> SourceBundle:
    """Write a validated program or closed source graph to a new directory.

    Binding keys match table paths (use a Path key for a table created from a Path).
    Relative string keys also expose files to SQL readers through file_search_path.
    SQL text and database identifiers without explicit bindings remain unchanged.
    The manifest records parameters, source identities and copied input hashes.
    """
    from pymalloy._headless.compiler import Compiler

    accepted = source if isinstance(source, Validation) else None
    if connection_name is not None and (
        not isinstance(connection_name, str) or not connection_name
    ):
        raise ValueError("connection_name must be a nonempty string")
    if accepted is not None and connection_name not in {None, accepted.connection_name}:
        raise ValueError(
            "Export connection differs from validation; validate the requested connection first"
        )
    connection_name = (
        accepted.connection_name
        if accepted is not None
        else connection_name or DEFAULT_CONNECTION
    )
    managed = []
    declared_files = dict(files or {})
    explicit_references = {table_path(key) for key in declared_files}
    if accepted is not None:
        accepted.require_valid()
        if query is not None and query not in accepted.queries:
            raise ValueError(f"Query {query!r} is not in the validated model")
        if givens is not None and encode_givens(givens) != encode_givens(
            accepted.givens
        ):
            raise ValueError(
                "Export parameters differ from validation; validate the requested bindings first"
            )
        givens = accepted.givens
        source = accepted.source
        for captured in accepted.draft.inputs:
            artifact = captured.materialize()
            if _hash(artifact.path) != artifact.sha256:
                raise ValueError(
                    f"Captured input {captured.name!r} changed after materialization"
                )
            if table_path(artifact.path) in explicit_references:
                raise ValueError(
                    "Explicit files cannot replace captured dataframe inputs"
                )
            declared_files[artifact.path] = artifact.path
            managed.append((captured, artifact))
    if not isinstance(source, ModelSource):
        raise TypeError("bundle requires a Validation or closed ModelSource snapshot")
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
    if source.document_kind != "model":
        raise ValueError("Source bundles require plain .malloy documents")

    # Import identity is distinct from the inline root, even when their URLs coincide.
    destinations = {
        url: PurePosixPath("sources")
        / (hashlib.sha256(url.encode()).hexdigest() + ".malloy")
        for url in source.imports
    }
    inputs = []
    bindings: dict[str, str] = {}
    managed_hashes = {
        table_path(artifact.path): artifact.sha256 for _, artifact in managed
    }
    aliases: dict[str, str | None] = {}
    for key, value in declared_files.items():
        if not isinstance(key, (str, Path)) or not str(key):
            raise TypeError("File bindings require string or Path keys")
        path = Path(value).resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"File binding is not a regular file: {path}")
        # Reuse the authoring API's distinction between file Paths and catalog strings.
        reference = table_path(key)
        alias = PurePosixPath(str(key))
        digest = managed_hashes.get(reference)
        if digest is not None:
            alias = PurePosixPath("inputs") / (digest + ".parquet")
        elif (
            not isinstance(key, str)
            or alias.is_absolute()
            or ".." in alias.parts
            or "\\" in key
            or ":" in key
            or (key.startswith("'") and key.endswith("'"))
        ):
            alias = PurePosixPath("__files__") / (
                hashlib.sha256(reference.encode()).hexdigest() + path.suffix
            )
        key_alias = str(alias).casefold()
        if str(alias) in {"", "."} or (
            key_alias in aliases and (digest is None or aliases[key_alias] != digest)
        ):
            raise ValueError(f"File bindings have a colliding destination: {key}")
        aliases[key_alias] = digest
        if reference in bindings:
            raise ValueError(f"Duplicate table binding: {reference}")
        bindings[reference] = str(alias)
        inputs.append((path, alias, reference))
    inputs.sort(key=lambda entry: entry[2])

    deadline = time.monotonic() + timeout
    documents = []
    compiler_version = None
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
                    FormatRequest(source=text),
                    FormatReady,
                    describe=lambda sql: [],
                    deadline=deadline,
                )
                if formatted.diagnostics:
                    raise CompilationError(
                        "Cannot format source bundle", diagnostics=formatted.diagnostics
                    )
                text = formatted.source
            parsed = compiler.parse(
                text, url=url, document_kind="model", deadline=deadline
            )
            compiler_version = parsed.compiler_version
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
            offsets = list(
                accumulate((len(line) + 1 for line in text.split("\n")), initial=0)
            )
            for reference in parsed.tables:
                if reference.path in bindings:
                    span = reference.range
                    start = offsets[span.start.line] + span.start.character
                    end = offsets[span.end.line] + span.end.character
                    edits.append(
                        (
                            start,
                            end,
                            table(
                                Path(bindings[reference.path]),
                                connection=reference.connection,
                            ).text,
                        )
                    )
            cursor = 0
            pieces = []
            for start, end, replacement in sorted(edits):
                if start < cursor or end > len(text) or end < start:
                    raise ValueError(
                        "Compiler source references overlap or are out of range"
                    )
                pieces.extend((text[cursor:start], replacement))
                cursor = end
            pieces.append(text[cursor:])
            text = "".join(pieces)
            documents.append((url, original, destination, text))
        syntax = from_wire(
            compiler.request(
                SyntaxRequest(
                    source=documents[0][3], url="memory://bundle/model.malloy"
                ),
                SyntaxReady,
                describe=lambda sql: [],
                deadline=deadline,
            ).syntax
        )
        if not isinstance(syntax, Fragment):
            raise TypeError("Compiler returned a scalar for a model document")
        python_model = Draft(
            syntax,
            "memory://bundle/model.malloy",
            {
                f"memory://bundle/{destination}": text
                for _, _, destination, text in documents[1:]
            },
        ).to_python()

    with tempfile.TemporaryDirectory(prefix=".pymalloy-", dir=target.parent) as staging:
        staged = Path(staging) / "bundle"
        staged.mkdir()
        (staged / "data").mkdir()
        (staged / "model.py").write_text(python_model)
        model_records = []
        for url, original, destination, text in documents:
            output = staged / destination
            output.parent.mkdir(parents=True, exist_ok=True)
            encoded = text.encode()
            output.write_bytes(encoded)
            model_records.append(
                {
                    "url": url,
                    "path": str(destination),
                    "sha256": hashlib.sha256(encoded).hexdigest(),
                    "original_sha256": hashlib.sha256(original.encode()).hexdigest(),
                }
            )
        file_records = []
        copied_hashes = {}
        files_by_reference = {}
        for path, alias, reference in inputs:
            output = staged / "data" / alias
            output.parent.mkdir(parents=True, exist_ok=True)
            if alias not in copied_hashes:
                shutil.copyfile(path, output)
                copied_hashes[alias] = _hash(output)
            record = {
                "reference": reference,
                "alias": str(alias),
                "path": str(PurePosixPath("data") / alias),
                "sha256": copied_hashes[alias],
            }
            file_records.append(record)
            files_by_reference[reference] = record
        input_records = []
        for captured, artifact in managed:
            reference = table_path(artifact.path)
            copied = files_by_reference[reference]
            if copied["sha256"] != artifact.sha256:
                raise ValueError(f"Input {captured.name!r} changed during export")
            input_records.append(
                {
                    "id": captured.id,
                    "name": captured.name,
                    "rows": captured.rows,
                    "schema": artifact.schema,
                    "arrow_schema": artifact.arrow_schema,
                    "snapshot_sha256": captured.fingerprint,
                    "path": copied["path"],
                    "sha256": artifact.sha256,
                }
            )
        assert compiler_version is not None  # originals always includes the root model.
        manifest = {
            "format_version": 3,
            "compiler_version": compiler_version,
            "model": "model.malloy",
            "data_root": "data",
            "connection_name": connection_name,
            "query": query,
            "givens": parameters,
            "sources": model_records,
            "files": file_records,
            "inputs": input_records,
            "validation": {
                "ok": True,
                "checks": [
                    {
                        "name": check.name,
                        "status": check.status,
                        "sql": check.result.sql if check.result else None,
                    }
                    for check in accepted.checks
                ],
            }
            if accepted is not None
            else None,
        }
        (staged / "replay.py").write_text(
            '"""Replay the selected query against frozen inputs."""\n'
            "import json\nfrom pathlib import Path\nimport pymalloy as pm\n\n"
            "root = Path(__file__).resolve().parent\n"
            'manifest = json.loads((root / "bundle.json").read_text())\n'
            'data_root = root / manifest["data_root"]\n'
            + file_guard('(entry["alias"] for entry in manifest["files"])')
            + "\ncheck_files()\n"
            'model = pm.model(root / manifest["model"], data_root=data_root, connection_name=manifest["connection_name"])\n'
            "try:\n"
            '    result = model.query(manifest["query"]).run(givens=manifest["givens"])\n'
            "finally:\n    model.close()\n"
        )
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
