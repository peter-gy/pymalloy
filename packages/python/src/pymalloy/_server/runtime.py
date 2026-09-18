from __future__ import annotations

import math
import threading
import time
import weakref
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb

from pymalloy._errors import ModelError
from pymalloy._givens import encode_givens
from pymalloy._records import (
    CheckReady,
    DocumentCell,
    DocumentReady,
    InspectionReady,
    ModelReady,
    QueryReady,
    SourceReady,
)
from pymalloy._selection import query_names
from pymalloy._source import ModelSource, resolve_source
from pymalloy.analysis import (
    CheckReport,
    Inspection,
    QueryDescriptor,
    SourcePosition,
)
from pymalloy.result import Result

from .compiler import Compiler
from .engine import Engine


def _close(compiler: Compiler, engine: Engine) -> None:
    try:
        compiler.close()
    finally:
        engine.close()


class _Runtime:
    """Compile and execute Malloy using an owned or borrowed DuckDB connection."""

    def __init__(
        self,
        *,
        data_root: str | Path | None = None,
        database: str | Path | None = None,
        connection: duckdb.DuckDBPyConnection | None = None,
        read_only: bool = False,
        timeout: float = 120,
        compiler_memory_mb: int = 256,
        deadline: float | None = None,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Model timeout must be finite and positive")
        deadline = deadline if deadline is not None else time.monotonic() + timeout
        self._engine = Engine(
            data_root=data_root,
            database=database,
            connection=connection,
            read_only=read_only,
        )
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Model startup exceeded its deadline")
            self._compiler = Compiler(memory_mb=compiler_memory_mb, timeout=remaining)
        except BaseException:
            self._engine.close()
            raise
        self.timeout = timeout
        self._root = Path(data_root or Path.cwd()).resolve()
        self._lock = threading.RLock()
        self._closed = False
        self._cleanup = weakref.finalize(self, _close, self._compiler, self._engine)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        return self._engine.connection

    @property
    def closed(self) -> bool:
        return self._closed

    def _check_open(self) -> None:
        if self._closed:
            raise ModelError("Model is closed. Create a new model.")

    @contextmanager
    def operation(
        self, timeout: float | None = None, *, deadline: float | None = None
    ) -> Iterator[float]:
        budget = self.timeout if timeout is None else timeout
        if not math.isfinite(budget) or budget <= 0:
            raise ValueError("Operation timeout must be finite and positive")
        deadline = deadline if deadline is not None else time.monotonic() + budget
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self._lock.acquire(timeout=remaining):
            raise TimeoutError("Waiting for the model exceeded its deadline")
        try:
            if time.monotonic() >= deadline:
                raise TimeoutError("Waiting for the model exceeded its deadline")
            self._check_open()
            expired = threading.Event()

            def interrupt() -> None:
                expired.set()
                try:
                    self.connection.interrupt()
                finally:
                    self._compiler.close()

            timer = threading.Timer(max(0, deadline - time.monotonic()), interrupt)
            timer.start()
            broken = False
            try:
                yield deadline
            except TimeoutError:
                expired.set()
                raise
            except (KeyboardInterrupt, SystemExit, ModelError):
                broken = True
                raise
            finally:
                timer.cancel()
                timer.join()
                if time.monotonic() >= deadline:
                    expired.set()
                if expired.is_set() or broken:
                    self.close()
                if expired.is_set():
                    raise TimeoutError(
                        f"Malloy operation exceeded {budget:g} seconds; model closed"
                    )
        finally:
            self._lock.release()

    def request[T](
        self,
        request: dict[str, Any],
        response_type: type[T],
        *,
        deadline: float,
        imports: Mapping[str, str] | None = None,
    ) -> T:
        return self._compiler.request(
            request,
            response_type,
            describe=self._engine.describe,
            deadline=deadline,
            imports=imports,
        )

    def compile(
        self,
        source: str | Path | ModelSource,
        *,
        url: str | None = None,
        deadline: float,
        tables: Mapping[str, Any] | None = None,
    ) -> Model:
        """Compile text, a Path, or a closed ModelSource snapshot."""
        identity, text, imports = resolve_source(source, url=url, root=self._root)
        with self.operation(deadline=deadline):
            for name, data in (tables or {}).items():
                self.connection.register(name, data)
            result = self.request(
                {"op": "begin", "url": identity, "source": text},
                ModelReady,
                deadline=deadline,
                imports=imports,
            )
            return Model(
                self,
                tuple(result.queries),
                imports,
            )

    def check(
        self,
        source: str | Path | ModelSource,
        *,
        path: str | Path | None = None,
        url: str | None = None,
        tables: Mapping[str, Any] | None = None,
        syntax_only: bool = False,
        position: SourcePosition | None = None,
        deadline: float,
    ) -> CheckReport:
        if type(syntax_only) is not bool:
            raise TypeError("syntax_only must be a boolean")
        if position is not None and not isinstance(position, SourcePosition):
            raise TypeError("position must be a SourcePosition")
        if path is not None and url is not None:
            raise ValueError("Choose path or url")
        identity, text, imports = resolve_source(
            source,
            url=Path(path).resolve().as_uri() if path is not None else url,
            root=self._root,
        )
        request: dict[str, Any] = {
            "op": "check",
            "source": text,
            "url": identity,
            "syntaxOnly": syntax_only,
        }
        if position is not None:
            request["position"] = {
                "line": position.line,
                "character": position.character,
            }
        with self.operation(deadline=deadline):
            for name, data in (tables or {}).items():
                self.connection.register(name, data)
            return self.request(
                request, CheckReady, deadline=deadline, imports=imports
            ).report

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._cleanup()


class Model:
    """Reusable compiled model created by `pymalloy.model`."""

    def __init__(
        self,
        runtime: _Runtime,
        queries: tuple[QueryDescriptor, ...],
        imports: Mapping[str, str] | None,
    ) -> None:
        self._owner = runtime
        self.queries = queries
        self._imports = imports

    def _request[T](
        self,
        request: dict[str, Any],
        response_type: type[T],
        timeout: float | None = None,
    ) -> T:
        with self._owner.operation(timeout) as deadline:
            return self._owner.request(
                request, response_type, deadline=deadline, imports=self._imports
            )

    def query(self, name: str | None = None, *, malloy: str | None = None) -> Query:
        self._owner._check_open()
        if name is not None and not isinstance(name, str):
            raise TypeError("Query name must be a string")
        if malloy is not None and not isinstance(malloy, str):
            raise TypeError("malloy must be query text")
        if name is not None and malloy is not None:
            raise ValueError("Choose a query name or Malloy text")
        if malloy is not None:
            return Query(
                self,
                QueryDescriptor(name="query", kind="run", location=None),
                {"malloy": malloy},
            )
        if name is None:
            runs = [q for q in self.queries if q.kind == "run"]
            name = (
                runs[-1].name
                if runs
                else self.queries[0].name
                if len(self.queries) == 1
                else None
            )
        info = next((q for q in self.queries if q.name == name), None)
        if info is None:
            raise ValueError(
                f"Choose a query from: {', '.join(q.name for q in self.queries)}"
            )
        return Query(self, info, info.name)

    def source(self, *, timeout: float | None = None) -> ModelSource:
        source = self._request({"op": "source"}, SourceReady, timeout).source
        return ModelSource(source.url, source.text, source.imports)

    def inspect(
        self,
        *,
        position: SourcePosition | None = None,
        url: str | None = None,
        timeout: float | None = None,
    ) -> Inspection:
        if position is not None and not isinstance(position, SourcePosition):
            raise TypeError("position must be a SourcePosition")
        if url is not None and not isinstance(url, str):
            raise TypeError("url must be a string")
        if url is not None and position is None:
            raise ValueError("url requires a position")
        request: dict[str, Any] = {"op": "inspect"}
        if position is not None:
            at: dict[str, Any] = {
                "line": position.line,
                "character": position.character,
            }
            if url is not None:
                at["url"] = url
            request["position"] = at
        return self._request(request, InspectionReady, timeout).inspection

    def document(
        self,
        *,
        queries: Sequence[str] | None = None,
        all: bool = False,
        givens: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> tuple[DocumentCell, ...]:
        names = query_names(queries, all=all)
        request: dict[str, Any] = {
            "op": "document",
            "all": all,
            "givens": encode_givens(givens),
        }
        if names is not None:
            request["queries"] = list(names)
        return tuple(self._request(request, DocumentReady, timeout).cells)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        self._owner._check_open()
        return self._owner.connection

    @property
    def closed(self) -> bool:
        return self._owner.closed

    def sql(
        self, *, givens: Mapping[str, Any] | None = None, timeout: float | None = None
    ) -> str:
        return self.query().sql(givens=givens, timeout=timeout)

    def run(
        self, *, givens: Mapping[str, Any] | None = None, timeout: float | None = None
    ) -> Result:
        return self.query().run(givens=givens, timeout=timeout)

    def close(self) -> None:
        self._owner.close()


class Query:
    """A query selection that retains its model and binds values per call."""

    def __init__(
        self, model: Model, info: QueryDescriptor, selection: str | dict[str, str]
    ) -> None:
        self._model = model
        self._selection = selection
        self.name, self.kind, self.location = info.name, info.kind, info.location

    def _sql(self, givens: Mapping[str, Any] | None, deadline: float) -> str:
        return self._model._owner.request(
            {
                "op": "query",
                "selection": self._selection,
                "givens": encode_givens(givens),
            },
            QueryReady,
            deadline=deadline,
            imports=self._model._imports,
        ).sql

    def sql(
        self, *, givens: Mapping[str, Any] | None = None, timeout: float | None = None
    ) -> str:
        with self._model._owner.operation(timeout) as deadline:
            return self._sql(givens, deadline)

    def run(
        self, *, givens: Mapping[str, Any] | None = None, timeout: float | None = None
    ) -> Result:
        runtime = self._model._owner
        with runtime.operation(timeout) as deadline:
            sql = self._sql(givens, deadline)
            if time.monotonic() >= deadline:
                raise TimeoutError("Query execution exceeded its deadline")
            return runtime._engine.run(sql)

    def preview(
        self,
        *,
        limit: int = 20,
        givens: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Result:
        """Execute a SELECT with an outer row limit. COPY is rejected before execution."""
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError("Preview limit must be an integer from 1 to 10000")
        runtime = self._model._owner
        with runtime.operation(timeout) as deadline:
            sql = self._sql(givens, deadline)
            if time.monotonic() >= deadline:
                raise TimeoutError("Query preview exceeded its deadline")
            return runtime._engine.preview(sql, limit)
