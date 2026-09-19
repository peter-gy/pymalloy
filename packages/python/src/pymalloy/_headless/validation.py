"""Execute draft assertions using the optional headless runtime."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Unpack

from pymalloy._authoring.syntax import Fragment
from pymalloy._model import DEFAULT_CONNECTION
from pymalloy._model.errors import CompilationError
from pymalloy._protocol.givens import encode_givens
from pymalloy.execution import ExecutionError
from pymalloy.validation import (
    DataCheck,
    DocumentationPolicy,
    Validation,
    _documentation,
)

if TYPE_CHECKING:
    from pymalloy._authoring.draft import Draft

    from .api import _RuntimeOptions


def validate(
    draft: Draft,
    checks: Mapping[str, Fragment],
    *,
    givens: Mapping[str, Any] | None,
    documentation: DocumentationPolicy | None = None,
    **options: Unpack[_RuntimeOptions],
) -> Validation:
    # One budget covers compilation, metadata, and every data assertion.
    deadline = time.monotonic() + options.get("timeout", 120)
    bindings = json.dumps(encode_givens(givens))
    connection_name = options.get("connection_name", DEFAULT_CONNECTION)
    selected = tuple(checks.items())
    if not all(
        isinstance(name, str)
        and name
        and isinstance(query, Fragment)
        and query.kind == "expression"
        for name, query in selected
    ):
        raise ValueError(
            "Checks must map nonempty names to symbolic source/query expressions"
        )
    skipped = tuple(DataCheck(name, "skipped") for name, _ in selected)
    try:
        model = draft.compile(**options)
    except CompilationError as error:
        return Validation(
            draft,
            tuple(error.diagnostics),
            skipped,
            str(error),
            bindings,
            connection_name=connection_name,
        )
    try:

        def remaining() -> float:
            value = deadline - time.monotonic()
            if value <= 0:
                raise TimeoutError("Model validation exceeded its deadline")
            return value

        captured = model.source(timeout=remaining())
        frozen = replace(draft, url=captured.url, imports=captured.imports)
        inspection = model.inspect(timeout=remaining())
        diagnostics = tuple(inspection.diagnostics) + _documentation(
            inspection.model, documentation
        )
        results = []
        for name, query in selected:
            try:
                result = model.query(query).preview(
                    limit=1, givens=givens, timeout=remaining()
                )
                results.append(
                    DataCheck(name, "failed" if result.rows() else "passed", result)
                )
            except (CompilationError, ExecutionError) as error:
                results.append(
                    DataCheck(
                        name,
                        "error",
                        error=str(error),
                        execution=error.context
                        if isinstance(error, ExecutionError)
                        else None,
                        diagnostics=tuple(error.diagnostics)
                        if isinstance(error, CompilationError)
                        else (),
                    )
                )
        return Validation(
            frozen,
            diagnostics,
            tuple(results),
            _givens_json=bindings,
            queries=tuple(query.name for query in model.queries),
            connection_name=connection_name,
        )
    except CompilationError as error:
        return Validation(
            draft, (), skipped, str(error), bindings, connection_name=connection_name
        )
    finally:
        model.close()
