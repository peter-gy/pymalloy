"""Detached evidence for reproducing a query execution failure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import msgspec

from pymalloy._model import DEFAULT_CONNECTION
from pymalloy._model.errors import PyMalloyError
from pymalloy._model.inputs import DataInput
from pymalloy._model.source import ModelSource
from pymalloy._protocol.givens import given_values
from pymalloy._protocol.records import Given
from pymalloy.analysis import QueryDescriptor


@dataclass(frozen=True)
class ExecutionContext:
    """Detached source and parameters for investigating an engine failure.

    Attributes
    ----------
    source : ModelSource
        Root source and captured imports at the failed execution.
    query : QueryDescriptor
        Selected query identity and authored location.
    malloy : str or None
        Ad hoc query text when the selection extended the model.
    sql : str
        Prepared SQL associated with the execution.
    compiler_version : str
        Malloy compiler version used to prepare the query.
    connection_name : str
        Connection identifier needed when reconstructing the runtime.
    givens : dict
        A detached copy of the exact bound values.
    preview_limit : int or None
        Output bound requested by preview, if any.

    Notes
    -----
    The context retains managed input owners, not arbitrary external table data.
    Replaying against a changed database or file can produce different results.
    """

    source: ModelSource
    query: QueryDescriptor
    malloy: str | None
    sql: str
    compiler_version: str
    connection_name: str = DEFAULT_CONNECTION
    preview_limit: int | None = None
    _givens_json: str = field(default="{}", repr=False)
    _inputs: tuple[DataInput, ...] = field(default=(), repr=False)

    @property
    def givens(self) -> dict[str, Any]:
        """Return a detached dictionary of exact values bound to the failed query."""
        return given_values(
            msgspec.json.decode(self._givens_json, type=dict[str, Given])
        )


class ExecutionError(PyMalloyError):
    """A data-engine failure with the source needed to investigate it.

    Attributes
    ----------
    context : ExecutionContext
        Captured source, SQL, selection and parameter bindings.
    __cause__ : Exception
        Original engine exception. Compiler diagnostics instead use CompilationError.

    See Also
    --------
    Query.run, Query.preview, ExecutionContext
    """

    def __init__(self, context: ExecutionContext, cause: Exception) -> None:
        self.context = context
        super().__init__(f"Query {context.query.name!r} execution failed: {cause}")
