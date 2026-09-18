"""Compiler-only tools, independent of the data engine and widget."""

import time
from contextlib import closing

from pymalloy._errors import CompilationError
from pymalloy._records import FormatReady, ParseReport, SyntaxNode, SyntaxReady

from .compiler import Compiler


def _format(compiler: Compiler, source: str, deadline: float) -> str:
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


def format(source: str) -> str:
    deadline = time.monotonic() + 30
    with closing(Compiler()) as compiler:
        return _format(compiler, source, deadline)


def parse(source: str, *, url: str) -> ParseReport:
    """Parse Malloy source and enumerate imports and table references."""
    deadline = time.monotonic() + 30
    with closing(Compiler()) as compiler:
        return compiler.parse(source, url=url, deadline=deadline)


def parse_syntax(source: str, *, url: str, format: bool = False) -> SyntaxNode:
    deadline = time.monotonic() + 30
    with closing(Compiler()) as compiler:
        if format:
            source = _format(compiler, source, deadline)
        return compiler.request(
            {"op": "syntax", "source": source, "url": url},
            SyntaxReady,
            describe=lambda sql: [],
            deadline=deadline,
        ).syntax
