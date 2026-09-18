from collections.abc import Sequence

from pymalloy.analysis import Diagnostic


class CompilationError(Exception):
    """Malloy could not resolve source, a query, or a data schema."""

    def __init__(self, message: str, *, diagnostics: Sequence[Diagnostic] = ()) -> None:
        super().__init__(message)
        self.diagnostics = tuple(diagnostics)


class SessionError(RuntimeError):
    """The session is closed or its Deno bridge is unavailable."""


class BridgeError(SessionError):
    """The Deno process or protocol failed."""
