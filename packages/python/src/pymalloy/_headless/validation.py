"""Execute draft assertions using the optional headless runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import msgspec

from pymalloy._authoring.draft import Draft
from pymalloy._protocol.givens import encode_givens, given_values
from pymalloy.authoring import Source
from pymalloy.errors import CompilationError, ExecutionError
from pymalloy.validation import (
    DataCheck,
    DocumentationPolicy,
    Validation,
    _documentation,
)

if TYPE_CHECKING:
    from .api import Connection


def validate(
    connection: Connection,
    draft: Draft,
    checks: Mapping[str, Source],
    *,
    givens: Mapping[str, Any] | None,
    documentation: DocumentationPolicy | None = None,
    deadline: float,
) -> Validation:
    if not isinstance(draft, Draft):
        raise TypeError("validate requires a Draft")
    encoded = encode_givens(givens)
    bindings = msgspec.json.encode(encoded).decode()
    connection_name = connection.name
    selected = tuple(checks.items())
    if not all(
        isinstance(name, str)
        and name
        and isinstance(query, Source)
        and query.kind == "expression"
        for name, query in selected
    ):
        raise ValueError("Checks must map nonempty names to symbolic Source values")
    skipped = tuple(DataCheck(name, "skipped") for name, _ in selected)
    try:
        model = connection._model(draft, deadline=deadline)
    except CompilationError as error:
        return Validation(
            draft,
            tuple(error.diagnostics),
            skipped,
            str(error),
            bindings,
            connection_name=connection_name,
        )
    frozen = draft
    try:
        captured = model.source()
        frozen = replace(draft, url=captured.url, imports=captured.imports)
        inspection = model._inspect(deadline=deadline)
        diagnostics = tuple(inspection.diagnostics) + _documentation(
            inspection.model, documentation
        )
        results = []
        for name, query in selected:
            try:
                result = model.query(query)._execute(given_values(encoded), deadline, 1)
                results.append(
                    DataCheck(
                        name, "failed" if result.to_pylist() else "passed", result
                    )
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
            frozen,
            tuple(error.diagnostics),
            skipped,
            str(error),
            bindings,
            connection_name=connection_name,
        )
    finally:
        model.close()
