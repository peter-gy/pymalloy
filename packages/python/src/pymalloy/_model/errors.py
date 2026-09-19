from collections.abc import Sequence

from pymalloy._protocol.records import Diagnostic


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
    check : Receive authored diagnostics in a CheckReport.
    CompilerError : Distinguish infrastructure failure from invalid source.
    """

    def __init__(self, message: str, *, diagnostics: Sequence[Diagnostic] = ()) -> None:
        super().__init__(message)
        self.diagnostics = tuple(diagnostics)


class ModelError(PyMalloyError):
    """The retained model is closed or its compiler is unavailable.

    Compile a fresh model before submitting further work. Materialized Result
    objects are independent of the model's lifetime.
    """


class CompilerError(ModelError):
    """The compiler process or protocol failed internally.

    This is a ModelError, distinct from authored CompilationError diagnostics.
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
