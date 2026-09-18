"""Execute draft assertions using the optional server runtime."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Unpack

import duckdb

from pymalloy._errors import CompilationError, ModelError
from pymalloy._syntax import Fragment
from pymalloy.validation import (
    _DEFAULT_DOCUMENTATION,
    DataCheck,
    DocumentationPolicy,
    Validation,
    _documentation,
)

if TYPE_CHECKING:
    from pymalloy._draft import Draft

    from .api import _RuntimeOptions


def validate(
    draft: Draft,
    checks: Mapping[str, Fragment],
    *,
    givens: Mapping[str, Any] | None,
    documentation: DocumentationPolicy | None = _DEFAULT_DOCUMENTATION,
    **options: Unpack[_RuntimeOptions],
) -> Validation:
    # One budget covers compilation, metadata, and every data assertion.
    deadline = time.monotonic() + options.get("timeout", 120)
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
        return Validation(draft, tuple(error.diagnostics), skipped, str(error))
    except (ModelError, TimeoutError) as error:
        return Validation(draft, (), skipped, str(error))
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
            except (
                CompilationError,
                ModelError,
                TimeoutError,
                ValueError,
                duckdb.Error,
            ) as error:
                results.append(
                    DataCheck(
                        name,
                        "error",
                        error=str(error),
                        diagnostics=tuple(error.diagnostics)
                        if isinstance(error, CompilationError)
                        else (),
                    )
                )
        return Validation(frozen, diagnostics, tuple(results))
    except (CompilationError, ModelError, TimeoutError) as error:
        return Validation(draft, (), skipped, str(error))
    finally:
        model.close()
