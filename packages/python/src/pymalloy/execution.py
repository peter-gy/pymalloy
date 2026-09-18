"""Detached evidence for reproducing a query execution failure."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pymalloy._givens import given_values
from pymalloy._source import ModelSource
from pymalloy.analysis import QueryDescriptor


@dataclass(frozen=True)
class ExecutionContext:
    """The model, query, bound parameters and SQL submitted to the engine."""

    source: ModelSource
    query: QueryDescriptor
    malloy: str | None
    sql: str
    compiler_version: str
    preview_limit: int | None = None
    _givens_json: str = field(default="{}", repr=False)

    @property
    def givens(self) -> dict[str, Any]:
        """A detached copy of the exact compiler bindings, including large integers."""
        return given_values(json.loads(self._givens_json))


class ExecutionError(RuntimeError):
    """Engine failure with replay context. The original exception is __cause__."""

    def __init__(self, context: ExecutionContext, cause: Exception) -> None:
        self.context = context
        super().__init__(f"Query {context.query.name!r} execution failed: {cause}")
