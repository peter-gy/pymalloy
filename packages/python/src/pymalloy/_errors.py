from collections.abc import Sequence

from pymalloy.analysis import Diagnostic


class PyMalloyError(RuntimeError):
    """Base class for failures reported by PyMalloy."""


class CompilationError(PyMalloyError):
    """Malloy could not resolve source, a query, or a data schema."""

    def __init__(self, message: str, *, diagnostics: Sequence[Diagnostic] = ()) -> None:
        super().__init__(message)
        self.diagnostics = tuple(diagnostics)


class ModelError(PyMalloyError):
    """The model is closed or its compiler is unavailable."""


class CompilerError(ModelError):
    """The compiler failed internally or its transport became unavailable."""


class SchemaError(PyMalloyError):
    """The data engine could not describe a compiler schema request."""

    def __init__(self, message: str, *, sql: str) -> None:
        self.sql = sql
        super().__init__(message)
