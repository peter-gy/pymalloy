"""Compiler-only tools, independent of the data engine and widget."""

import time
from contextlib import closing

from pymalloy._errors import CompilationError
from pymalloy._records import FormatReady, ParseReport

from .compiler import Compiler


def format(source: str) -> str:
    deadline = time.monotonic() + 30
    with closing(Compiler()) as compiler:
        result = compiler.request(
            {"op": "format", "source": source},
            FormatReady,
            describe=lambda sql: [],
            deadline=deadline,
        )
        if result.diagnostics:
            raise CompilationError(
                "Malloy formatting failed",
                diagnostics=result.diagnostics,
            )
        return result.source


def parse(source: str, *, url: str) -> ParseReport:
    """Parse Malloy source and enumerate imports and table references."""
    deadline = time.monotonic() + 30
    with closing(Compiler()) as compiler:
        return compiler.parse(source, url=url, deadline=deadline)
