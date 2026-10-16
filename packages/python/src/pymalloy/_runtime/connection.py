from __future__ import annotations

import os
import threading
import weakref
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Self

import duckdb as native_duckdb

from pymalloy._authoring.draft import Draft
from pymalloy._compiler.host import Compiler
from pymalloy._compiler.tooling import compiler_lease
from pymalloy._model import DEFAULT_CONNECTION
from pymalloy._model.source import DocumentKind, ModelSource
from pymalloy.analysis import CheckReport, SourcePosition
from pymalloy.authoring import Source
from pymalloy.errors import ClosedError
from pymalloy.validation import DocumentationPolicy, Validation, _checked

from .engine import Engine
from .model import Model, Query, _Runtime, deadline_after

__all__ = ["Connection", "Model", "Query", "connect"]


class Connection:
    """Own native DuckDB execution and the lifetimes of compiled models.

    Construct with ``pm.connect()``. Models and queries retain their connection.
    Closing a model releases its compiler. Closing the connection settles work,
    closes its child models, and closes an owned DuckDB connection.
    """

    _name: str
    _timeout: float
    _compiler_memory_mb: int
    _root: Path
    _lock: threading.RLock
    _engine: Engine
    _cleanup: weakref.finalize
    _runtimes: weakref.WeakSet[_Runtime]
    _pid: int
    _operations: threading.local

    def __new__(cls):
        raise TypeError("Create connections with pm.connect()")

    @classmethod
    def _open(
        cls,
        database: str | Path | native_duckdb.DuckDBPyConnection = ":memory:",
        *,
        data_root: str | Path | None = None,
        read_only: bool = False,
        config: Mapping[str, Any] | None = None,
        extensions: Sequence[str] = (),
        name: str = DEFAULT_CONNECTION,
        timeout: float = 120,
        compiler_memory_mb: int = 256,
        deadline: float,
    ) -> Self:
        self = object.__new__(cls)
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a nonempty string")
        if type(compiler_memory_mb) is not int or compiler_memory_mb <= 0:
            raise ValueError("compiler_memory_mb must be a positive integer")
        self._name = name
        self._pid = os.getpid()
        self._operations = threading.local()
        self._timeout = timeout
        self._compiler_memory_mb = compiler_memory_mb
        self._root = Path(data_root or Path.cwd()).resolve()
        self._lock = threading.RLock()
        self._closed = False
        self._runtimes = weakref.WeakSet()
        borrowed = isinstance(database, native_duckdb.DuckDBPyConnection)
        self._engine = Engine(
            connection=database if borrowed else None,
            database=None if borrowed else database,
            data_root=data_root,
            config=config,
            extensions=extensions,
            read_only=read_only,
            deadline=deadline,
        )
        self._cleanup = weakref.finalize(self, self._engine.close)
        return self

    @property
    def name(self) -> str:
        """Return the Malloy connection identifier."""
        return self._name

    @property
    def duckdb(self) -> native_duckdb.DuckDBPyConnection:
        """Return the native connection while this owner is open."""
        self._check_open()
        return self._engine.connection

    @property
    def closed(self) -> bool:
        """Return whether this connection has closed."""
        return self._closed or self._pid != os.getpid()

    def _check_open(self) -> None:
        if self._pid != os.getpid():
            raise ClosedError(
                "Connections cannot be reused after fork. "
                "Start a fresh process with spawn."
            )
        if self._closed:
            raise ClosedError("Connection is closed. Create a new connection.")

    def _check_operation(self) -> None:
        self._check_open()
        if getattr(self._operations, "active", False):
            raise ClosedError("Connection operations cannot reenter their active owner")

    def _deadline(self, timeout: float | None) -> float:
        return deadline_after(self._timeout if timeout is None else timeout)

    def _model(
        self,
        source: str | Path | ModelSource | Draft,
        *,
        url: str | None = None,
        document_kind: DocumentKind | None = None,
        timeout: float | None = None,
        deadline: float,
        compiler: Compiler | None = None,
    ) -> Model:
        self._check_operation()
        runtime = _Runtime(
            self,
            timeout=self._timeout if timeout is None else timeout,
            deadline=deadline,
            compiler=compiler,
        )
        try:
            return runtime.compile(
                source, url=url, document_kind=document_kind, deadline=deadline
            )
        except BaseException:
            runtime.close()
            raise

    def model(
        self,
        source: str | Path | ModelSource | Draft,
        *,
        url: str | None = None,
        document_kind: DocumentKind | None = None,
        timeout: float | None = None,
    ) -> Model:
        """Compile source using this connection's engine.

        Parameters
        ----------
        source : str, pathlib.Path, ModelSource, or Draft
            Malloy text, a file, a closed source graph, or an authored revision.
        url : str, optional
            Identity for inline text. Must agree with a source carrying identity.
        document_kind : {"model", "notebook"}, optional
            Grammar override, otherwise inferred from source identity.
        timeout : float, optional
            Compilation and default model operation budget in seconds.
            None uses the connection default.

        Returns
        -------
        Model
            Compiled source and query inventory owning one native compiler.
        """
        return self._model(
            source,
            url=url,
            document_kind=document_kind,
            timeout=timeout,
            deadline=self._deadline(timeout),
        )

    def check(
        self,
        source: str | Path | ModelSource | Draft,
        *,
        url: str | None = None,
        document_kind: DocumentKind | None = None,
        position: SourcePosition | None = None,
        documentation: DocumentationPolicy | None = None,
        timeout: float | None = None,
    ) -> CheckReport:
        """Check syntax, names, types, and schemas against this connection.

        Parameters
        ----------
        source : str, pathlib.Path, ModelSource, or Draft
            Source accepted by model.
        url : str, optional
            Identity for inline text.
        document_kind : {"model", "notebook"}, optional
            Grammar override.
        position : SourcePosition, optional
            Zero-based line and code-point position for completions and help.
        documentation : DocumentationPolicy, optional
            Description-presence policy from pymalloy.validation.
        timeout : float, optional
            Budget in seconds, defaulting to the connection's timeout.

        Returns
        -------
        CheckReport
            Structured diagnostics, schema metadata, and query inventory.
        """
        self._check_operation()
        deadline = self._deadline(timeout)
        with compiler_lease(deadline, memory_mb=self._compiler_memory_mb) as compiler:
            runtime = _Runtime(
                self,
                timeout=self._timeout,
                deadline=deadline,
                compiler=compiler,
                own_compiler=False,
            )
            try:
                return _checked(
                    runtime.check(
                        source,
                        url=url,
                        document_kind=document_kind,
                        position=position,
                        deadline=deadline,
                    ),
                    documentation,
                )
            finally:
                runtime.close()

    def validate(
        self,
        draft: Draft,
        checks: Mapping[str, Source] | None = None,
        *,
        givens: Mapping[str, Any] | None = None,
        documentation: DocumentationPolicy | None = None,
        timeout: float | None = None,
    ) -> Validation:
        """Capture bindings once and run counterexample queries on a draft.

        Zero rows passes a check. A failed check retains one counterexample.
        One deadline covers compilation, inspection, and every check.
        """
        from .validation import validate

        self._check_operation()
        return validate(
            self,
            draft,
            checks if checks is not None else {},
            givens=givens,
            documentation=documentation,
            deadline=self._deadline(timeout),
        )

    def close(self) -> None:
        """Settle work, close child models, and release the owned native engine."""
        if self._pid != os.getpid():
            self._closed = True
            self._engine.close()
            self._cleanup.detach()
            return
        with self._lock:
            if not self._closed:
                self._closed = True
                for runtime in tuple(self._runtimes):
                    runtime.close()
                self._cleanup()

    def __enter__(self) -> Self:
        self._check_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def connect(
    database: str | Path | native_duckdb.DuckDBPyConnection = ":memory:",
    *,
    data_root: str | Path | None = None,
    read_only: bool = False,
    config: Mapping[str, Any] | None = None,
    extensions: Sequence[str] = (),
    name: str = DEFAULT_CONNECTION,
    timeout: float = 120,
    compiler_memory_mb: int = 256,
) -> Connection:
    """Open a native runtime owner or borrow an existing DuckDB connection.

    Parameters
    ----------
    database : str, pathlib.Path, or duckdb.DuckDBPyConnection, default ":memory:"
        Database to open, or an existing connection to borrow. Borrowed settings,
        registrations, and transactions remain caller-owned.
    data_root : str or pathlib.Path, optional
        Relative data search directory on an owned connection.
    read_only : bool, default False
        Open an owned database for reading.
    config : mapping, optional
        DuckDB settings for an owned connection. Defaults include UTC.
    extensions : sequence of str, default ()
        Extensions to install and load before file-access restrictions.
    name : str, default "duckdb"
        Malloy connection name matching authoring constructors' connection=.
    timeout : float, default 120
        Positive finite operation budget in seconds.
    compiler_memory_mb : int, default 256
        Per-model managed JavaScript heap budget in MiB. Fatal native engine
        failures affect the Python process.

    Returns
    -------
    Connection
        Engine owner with model compilation, checking, and validation methods.
        Closing it settles child models before releasing an owned engine.

    Raises
    ------
    ValueError
        Options conflict, or data_root, read_only=True, config, or extensions are
        supplied with a borrowed connection.

    Notes
    -----
    A failed statement, including a timeout, can abort an open transaction on a
    borrowed connection. Subsequent operations report the aborted transaction.
    The caller must issue ROLLBACK before reusing that transaction. PyMalloy leaves
    COMMIT and ROLLBACK to the caller.

    Examples
    --------
    >>> import pymalloy as pm
    >>> with pm.connect() as con:
    ...     result = con.model("run: duckdb.sql('SELECT 42 AS n') -> {select: n}").query().run()
    >>> result.to_pylist()
    [{'n': 42}]
    """
    return Connection._open(
        database,
        data_root=data_root,
        read_only=read_only,
        config=config,
        extensions=extensions,
        name=name,
        timeout=timeout,
        compiler_memory_mb=compiler_memory_mb,
        deadline=deadline_after(timeout),
    )
