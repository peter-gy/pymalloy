"""Compiler-only tools, independent of the data engine and widget."""

import atexit
import os
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from pymalloy._authoring.draft import Draft
from pymalloy._model.source import DocumentKind, ModelSource, open_source
from pymalloy._protocol.records import (
    FormatReady,
    FormatRequest,
    ParseReport,
    SyntaxNode,
    SyntaxReady,
    SyntaxRequest,
)
from pymalloy.errors import CompilationError, CompilerError

from .host import Compiler

_IDLE_SECONDS = 30.0


class _ToolingCompiler:
    """One serialized compiler, released after thirty seconds without a lease."""

    def __init__(self) -> None:
        self._pid = os.getpid()
        self._operations = threading.local()
        self._lock = threading.RLock()
        self._compiler: Compiler | None = None
        self._memory_mb = 256
        self._timer: threading.Timer | None = None
        self._idle_until = 0.0

    @contextmanager
    def lease(self, deadline: float, memory_mb: int) -> Generator[Compiler, None, None]:
        if self._pid != os.getpid():
            raise CompilerError(
                "Compiler tooling cannot be reused after fork. "
                "Start a fresh process with spawn."
            )
        if getattr(self._operations, "active", False):
            raise CompilerError("Compiler tooling cannot reenter its active owner")
        # Signals can run Python between lock acquisition and the next statement.
        try:
            self._operations.active = True
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self._lock.acquire(timeout=remaining):
                raise TimeoutError(
                    "Waiting for the tooling compiler exceeded its deadline"
                )
            try:
                if deadline <= time.monotonic():
                    raise TimeoutError(
                        "Waiting for the tooling compiler exceeded its deadline"
                    )
                if self._compiler is not None and (
                    self._compiler.closed or memory_mb != self._memory_mb
                ):
                    self._close()
                if self._compiler is None:
                    self._compiler = Compiler(memory_mb=memory_mb)
                    self._memory_mb = memory_mb
                try:
                    yield self._compiler
                except CompilationError:
                    raise
                except BaseException:
                    self._close()
                    raise
            finally:
                try:
                    if self._compiler is not None:
                        self._compiler.sources.clear()
                        self._idle_until = time.monotonic() + _IDLE_SECONDS
                        if self._timer is None:
                            self._schedule(_IDLE_SECONDS)
                finally:
                    self._lock.release()
        finally:
            self._operations.active = False

    def _schedule(self, delay: float) -> None:
        def expire() -> None:
            with self._lock:
                if self._timer is not timer:
                    return
                self._timer = None
                remaining = self._idle_until - time.monotonic()
                if remaining > 0:
                    self._schedule(remaining)
                else:
                    self._close()

        timer = threading.Timer(delay, expire)
        timer.daemon = True
        self._timer = timer
        try:
            timer.start()
        except RuntimeError:
            self._timer = None
            self._close()

    def _close(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._compiler is not None:
            compiler = self._compiler
            self._compiler = None
            compiler.close()

    def close(self) -> None:
        if self._pid != os.getpid():
            return
        active = getattr(self._operations, "active", False)
        try:
            self._operations.active = True
            with self._lock:
                self._close()
        finally:
            self._operations.active = active


_tooling = _ToolingCompiler()
atexit.register(_tooling.close)


def compiler_lease(deadline: float, memory_mb: int = 256):
    return _tooling.lease(deadline, memory_mb)


def _format(compiler: Compiler, source: str, deadline: float) -> str:
    result = compiler.request(
        FormatRequest(source=source),
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
    """Format Malloy source using the installed compiler's formatter.

    Parameters
    ----------
    source : str
        Plain Malloy source text compiled by the installed native compiler.

    Returns
    -------
    str
        Formatted source. A shared tooling compiler is reused and expires when idle.

    Raises
    ------
    CompilationError
        The source cannot be formatted, with native compiler diagnostics.

    Examples
    --------
    >>> import pymalloy as pm
    >>> formatted = pm.format("source: values is duckdb.sql('SELECT 42 AS n')")
    >>> pm.format(formatted) == formatted
    True
    """
    deadline = time.monotonic() + 30
    with compiler_lease(deadline) as compiler:
        return _format(compiler, source, deadline)


def parse(
    source: str | Path | ModelSource | Draft,
    *,
    url: str | None = None,
    document_kind: DocumentKind | None = None,
) -> ParseReport:
    """Parse source and return locations, symbols, imports and table references.

    Parameters
    ----------
    source : str, pathlib.Path, ModelSource, or Draft
        Malloy text, a local file, a closed source graph, or an authored revision.
    url : str, optional
        Absolute identity for inline text, otherwise supplied by the source.
        Inline text defaults to model.malloy in the current directory.
    document_kind : {"model", "notebook"}, optional
        Override extension-based classification of the supplied URL.

    Returns
    -------
    ParseReport
        Syntax diagnostics and tooling metadata. Undefined sources and fields
        require semantic checking with check. Imported source is not loaded.

    Notes
    -----
    Coordinates are zero-based Unicode code-point offsets rather than
    JavaScript UTF-16 units. Parsing opens no DuckDB connection.

    Examples
    --------
    >>> import pymalloy as pm
    >>> report = pm.parse("run: missing_source", url="memory://tour/model.malloy")
    >>> len(report.diagnostics)
    0
    >>> pm.connect().check('run: missing_source').ok
    False
    """
    deadline = time.monotonic() + 30
    identity, text, _, kind = open_source(
        source, url=url, document_kind=document_kind, root=Path.cwd()
    )
    with compiler_lease(deadline) as compiler:
        return compiler.parse(text, url=identity, document_kind=kind, deadline=deadline)


def parse_syntax(source: str, *, url: str, format: bool = False) -> SyntaxNode:
    deadline = time.monotonic() + 30
    with compiler_lease(deadline) as compiler:
        if format:
            source = _format(compiler, source, deadline)
        return compiler.request(
            SyntaxRequest(source=source, url=url),
            SyntaxReady,
            describe=lambda sql: [],
            deadline=deadline,
        ).syntax
