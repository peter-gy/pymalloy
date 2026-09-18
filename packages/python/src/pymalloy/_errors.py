from collections.abc import Sequence

from pymalloy.analysis import Diagnostic


class CompilationError(Exception):
    """Malloy could not resolve source, a query, or a data schema."""

    def __init__(self, message: str, *, diagnostics: Sequence[Diagnostic] = ()) -> None:
        super().__init__(message)
        self.diagnostics = tuple(diagnostics)


class ModelError(RuntimeError):
    """The model is closed or its compiler is unavailable."""


class SchemaError(RuntimeError):
    """The data engine could not describe a compiler schema request."""

    def __init__(self, message: str, *, sql: str) -> None:
        self.sql = sql
        super().__init__(message)
