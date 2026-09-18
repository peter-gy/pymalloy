from __future__ import annotations

import math
import threading
import time
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Self

import duckdb

from pymalloy.server._bridge import Bridge
from pymalloy.server._data import DataAccess
from pymalloy.server._errors import BridgeError, SessionError


def _close_resources(
    bridge: Bridge, connection: duckdb.DuckDBPyConnection | None
) -> None:
    try:
        bridge.close()
    finally:
        if connection is not None:
            connection.close()


class NativeRuntime:
    """Own a native connection, compiler process, and serialized operation budget."""

    def __init__(
        self,
        *,
        data_root: str | Path | None = None,
        database: str | Path | None = None,
        connection: duckdb.DuckDBPyConnection | None = None,
        read_only: bool = False,
        timeout: float = 120,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Session timeout must be finite and positive")
        if connection is not None and (database is not None or read_only):
            raise ValueError("Pass connection or database/read_only, not both")
        self._data_root = Path(data_root).resolve() if data_root is not None else None
        if self._data_root is not None and not self._data_root.is_dir():
            raise ValueError(f"Data directory does not exist: {self._data_root}")
        self._owns_connection = connection is None
        self._connection = (
            connection
            if connection is not None
            else duckdb.connect(
                str(database) if database is not None else ":memory:",
                read_only=read_only,
            )
        )
        if self._owns_connection:
            self.connection.execute("SET TimeZone='UTC'")
        self._data = DataAccess(self.connection)
        self.timeout = timeout
        self._bridge = Bridge()
        self._lock = threading.RLock()
        self._closed = False
        self._cleanup = weakref.finalize(
            self,
            _close_resources,
            self._bridge,
            self._connection if self._owns_connection else None,
        )

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """The DuckDB connection selected at construction."""
        return self._connection

    @property
    def closed(self) -> bool:
        return self._closed

    def _check_open(self) -> None:
        if self._closed:
            raise SessionError("Session is closed. Create a new Session.")

    @contextmanager
    def _operation(self, timeout: float | None = None) -> Iterator[None]:
        budget = self.timeout if timeout is None else timeout
        if not math.isfinite(budget) or budget <= 0:
            raise ValueError("Operation timeout must be finite and positive")
        started = time.monotonic()
        if not self._lock.acquire(timeout=budget):
            raise TimeoutError(f"Waiting for the session exceeded {budget:g} seconds")
        try:
            self._check_open()
            expired = threading.Event()
            broken = False
            interrupted = False

            def expire() -> None:
                expired.set()
                self._bridge.terminate()
                self.connection.interrupt()

            timer = threading.Timer(
                max(0, budget - (time.monotonic() - started)), expire
            )
            timer.start()
            try:
                yield
            except (BridgeError, KeyboardInterrupt, SystemExit) as error:
                broken = True
                interrupted = isinstance(error, (KeyboardInterrupt, SystemExit))
                self._bridge.terminate()
                raise
            finally:
                timer.cancel()
                timer.join()
                if expired.is_set() or broken:
                    self.close()
                if expired.is_set() and not interrupted:
                    raise TimeoutError(
                        f"Malloy operation exceeded {budget:g} seconds; session closed"
                    )
        finally:
            self._lock.release()

    def _request(self, request: dict[str, Any], root: Path) -> dict[str, Any]:
        return self._bridge.request(request, lambda sql: self._data.describe(sql, root))

    def close(self) -> None:
        """Release Deno models and the owned connection. Borrowed connections stay open."""
        with self._lock:
            if not self._closed:
                self._closed = True
                self._cleanup()

    def __enter__(self) -> Self:
        self._check_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
