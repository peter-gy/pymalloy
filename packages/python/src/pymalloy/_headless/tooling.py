"""Compiler-only tools, independent of the data engine and widget."""

import atexit
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager

from pymalloy._model.errors import CompilationError
from pymalloy._model.source import DocumentKind
from pymalloy._protocol.records import (
    FormatReady,
    FormatRequest,
    ParseReport,
    SyntaxNode,
    SyntaxReady,
    SyntaxRequest,
)

from .compiler import Compiler

_IDLE_SECONDS = 30.0


class _ToolingCompiler:
    """One serialized compiler, released after thirty seconds without a lease."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._compiler: Compiler | None = None
        self._memory_mb = 256
        self._timer: threading.Timer | None = None
        self._idle_until = 0.0

    @contextmanager
    def lease(self, deadline: float, memory_mb: int) -> Generator[Compiler, None, None]:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self._lock.acquire(timeout=remaining):
            raise TimeoutError("Waiting for the tooling compiler exceeded its deadline")
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    "Waiting for the tooling compiler exceeded its deadline"
                )
            if self._compiler is not None and (
                self._compiler.closed or memory_mb != self._memory_mb
            ):
                self._close()
            if self._compiler is None:
                self._compiler = Compiler(memory_mb=memory_mb, timeout=remaining)
                self._memory_mb = memory_mb
            try:
                yield self._compiler
            except CompilationError:
                # The service has settled a diagnostic response and remains reusable.
                raise
            except BaseException:
                self._close()
                raise
        finally:
            if self._compiler is not None:
                self._compiler.sources.clear()
                self._idle_until = time.monotonic() + _IDLE_SECONDS
                if self._timer is None:
                    self._schedule(_IDLE_SECONDS)
            self._lock.release()

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
        timer.start()

    def _close(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._compiler is not None:
            self._compiler.close()
            self._compiler = None

    def close(self) -> None:
        with self._lock:
            self._close()


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
        Plain Malloy source text. Requires pymalloy[headless] for the compiler,
        but this operation opens no DuckDB connection.

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
    source: str, *, url: str, document_kind: DocumentKind | None = None
) -> ParseReport:
    """Parse source and return locations, symbols, imports and table references.

    Parameters
    ----------
    source : str
        Malloy model or notebook-document text.
    url : str
        Absolute identity used in source locations and import URLs.
    document_kind : {"model", "notebook"}, optional
        Override extension-based classification of the supplied URL.

    Returns
    -------
    ParseReport
        Syntax diagnostics and tooling metadata. Undefined sources and fields
        require semantic checking with check. Imported source is not loaded.

    Notes
    -----
    Requires the headless compiler but opens no DuckDB connection. Coordinates
    are zero-based Unicode code-point offsets rather than JavaScript UTF-16 units.

    Examples
    --------
    >>> import pymalloy as pm
    >>> report = pm.parse("run: missing_source", url="memory://tour/model.malloy")
    >>> len(report.diagnostics)
    0
    >>> pm.check("run: missing_source").ok
    False
    """
    deadline = time.monotonic() + 30
    with compiler_lease(deadline) as compiler:
        return compiler.parse(
            source, url=url, document_kind=document_kind, deadline=deadline
        )


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
