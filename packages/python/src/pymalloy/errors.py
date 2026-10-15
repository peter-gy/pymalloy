"""Domain failures and detached query execution evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import msgspec

from pymalloy._model import DEFAULT_CONNECTION
from pymalloy._model.inputs import Input
from pymalloy._model.source import ModelSource
from pymalloy._protocol.givens import given_values
from pymalloy._protocol.records import Given
from pymalloy._protocol.snapshot import freeze
from pymalloy.analysis import Diagnostic, QueryDescriptor

if TYPE_CHECKING:
    from pymalloy.validation import Validation

__all__ = [
    "ClosedError",
    "CompilationError",
    "CompilerError",
    "ExecutionContext",
    "ExecutionError",
    "PyMalloyError",
    "SchemaError",
    "ValidationError",
]


class PyMalloyError(RuntimeError):
    """Base exception for PyMalloy domain failures.

    Catch this to handle authored compilation, runtime ownership, schema and
    execution failures together. Operational OSError and TimeoutError remain
    separate Python exceptions so callers can choose a different recovery path.
    """


class CompilationError(PyMalloyError):
    """Malloy could not resolve authored source, a query or a data schema.

    Attributes
    ----------
    diagnostics : tuple of Diagnostic
        Structured compiler messages with codes, severity and source locations
        when available. Inspect them to locate a user-authored error.

    See Also
    --------
    Connection.check : Receive authored diagnostics in a CheckReport.
    CompilerError : Distinguish infrastructure failure from invalid source.
    """

    def __init__(self, message: str, *, diagnostics: Sequence[Diagnostic] = ()) -> None:
        if any(item.code == "compiler-given-no-value" for item in diagnostics):
            message += (
                "\nIn Python, bind values with Query.run(givens={...}) or declare"
                " a default in the model."
            )
        super().__init__(message)
        self.diagnostics = tuple(diagnostics)


class ClosedError(PyMalloyError):
    """The Connection, Model, or Query has closed.

    Compile a fresh model before submitting further work. Materialized Result
    objects are independent of the model's lifetime.
    """


class CompilerError(PyMalloyError):
    """The compiler process or protocol failed internally.

    The affected compiler is closed. Retrying requires a fresh runtime.
    """


class SchemaError(PyMalloyError):
    """A data engine could not describe a compiler schema request.

    Attributes
    ----------
    sql : str
        Schema-discovery SQL associated with the failure.

    The compiler may attach the native failure as a cause to authored diagnostics.
    """

    def __init__(self, message: str, *, sql: str) -> None:
        self.sql = sql
        super().__init__(message)


@dataclass(frozen=True, init=False)
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
    givens : mapping
        Read-only exact bindings captured for the failed query.
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
    _inputs: tuple[Input, ...] = field(default=(), repr=False)

    def __new__(cls):
        raise TypeError("ExecutionContext is produced by query execution")

    @classmethod
    def _create(
        cls,
        *,
        source: ModelSource,
        query: QueryDescriptor,
        malloy: str | None,
        sql: str,
        compiler_version: str,
        connection_name: str,
        preview_limit: int | None,
        _givens_json: str,
        _inputs: tuple[Input, ...],
    ) -> ExecutionContext:
        context = object.__new__(cls)
        for name, value in (
            ("source", source),
            ("query", query),
            ("malloy", malloy),
            ("sql", sql),
            ("compiler_version", compiler_version),
            ("connection_name", connection_name),
            ("preview_limit", preview_limit),
            ("_givens_json", _givens_json),
            ("_inputs", _inputs),
        ):
            object.__setattr__(context, name, value)
        return context

    @property
    def givens(self) -> Mapping[str, Any]:
        """Return recursively immutable values bound to the failed query."""
        return freeze(
            given_values(msgspec.json.decode(self._givens_json, type=dict[str, Given]))
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


class ValidationError(PyMalloyError):
    """A rejected validation report, available through ``report``."""

    def __init__(self, report: Validation, message: str) -> None:
        self.report = report
        super().__init__(message)
