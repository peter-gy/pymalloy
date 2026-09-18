from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Self

import polars as pl

from pymalloy._source import ModelSource
from pymalloy.analysis import CheckResult, Diagnostic, Position
from pymalloy.server._errors import CompilationError, SessionError
from pymalloy.server._givens import encode_givens
from pymalloy.server._runtime import NativeRuntime


class Session(NativeRuntime):
    """Execute Malloy using an owned or borrowed native DuckDB connection.

    `data_root` resolves relative data files. `database` opens an owned connection,
    optionally `read_only`. `connection` borrows an existing connection.
    Each operation has a `timeout` in seconds. Use a context manager or `close()`.
    """

    def check(
        self,
        source: str,
        *,
        path: str | Path | None = None,
        syntax_only: bool = False,
        position: Position | None = None,
        timeout: float | None = None,
    ) -> CheckResult:
        """Check source and return diagnostics, symbols, and model metadata.

        `path` identifies source and resolves imports. Semantic checking discovers
        data schemas. `syntax_only` parses source without reading data or imports.
        `position` requests native completions and help at that source location.
        """
        if not isinstance(source, str):
            raise TypeError(
                "source must be Malloy text. Use check_file(path) for files."
            )
        if position is not None and not isinstance(position, Position):
            raise TypeError("position must be a Position")
        if type(syntax_only) is not bool:
            raise TypeError("syntax_only must be a boolean")
        identity = (
            Path(path).resolve()
            if path is not None
            else (self._data_root or Path.cwd()) / "inline.malloy"
        )
        with self._operation(timeout):
            response = self._request(
                {
                    "op": "check",
                    "url": identity.as_uri(),
                    "source": source,
                    "syntax_only": syntax_only,
                    "position": {"line": position.line, "character": position.character}
                    if position
                    else None,
                },
                self._data_root or identity.parent,
            )
            return CheckResult._from_wire(response)

    def check_file(
        self,
        path: str | Path,
        *,
        syntax_only: bool = False,
        position: Position | None = None,
        timeout: float | None = None,
    ) -> CheckResult:
        """Read a local model or document and check its source."""
        path = Path(path).resolve()
        return self.check(
            path.read_text(encoding="utf-8"),
            path=path,
            syntax_only=syntax_only,
            position=position,
            timeout=timeout,
        )

    def format(self, source: str, *, timeout: float | None = None) -> str:
        """Format Malloy source with its experimental upstream formatter.

        Raises `CompilationError` with diagnostics for malformed source. This
        operation parses source and does not discover schemas or execute SQL.
        """
        if not isinstance(source, str):
            raise TypeError("source must be Malloy text")
        with self._operation(timeout):
            response = self._request(
                {"op": "format", "source": source}, self._data_root or Path.cwd()
            )
        diagnostics = tuple(
            Diagnostic._from_wire(item) for item in response["diagnostics"]
        )
        if any(item.severity == "error" for item in diagnostics):
            raise CompilationError("Malloy formatting failed", diagnostics=diagnostics)
        return response["source"]

    def model(self, source: str, *, base_dir: str | Path | None = None) -> Model:
        """Load inline Malloy source. `base_dir` resolves its local imports."""
        if not isinstance(source, str):
            raise TypeError("source must be Malloy text. Use load(path) for files.")
        base = (
            Path(base_dir).resolve()
            if base_dir is not None
            else self._data_root or Path.cwd()
        )
        with self._operation():
            return self._load((base / "inline.malloy"), source)

    def load(self, path: str | Path) -> Model:
        """Load a local model or notebook. Imports resolve beside that file."""
        path = Path(path).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        with self._operation():
            return self._load(path)

    def load_source(self, source: ModelSource) -> Model:
        """Hydrate a captured model using its source snapshot and this session's data.

        Imports resolve exclusively from the captured sources. The session's
        data_root, or the current directory, resolves relative data files.
        """
        if not isinstance(source, ModelSource):
            raise TypeError("source must be a ModelSource")
        root = self._data_root or Path.cwd()
        with self._operation():
            response = self._request(
                {
                    "op": "load",
                    "url": source.url,
                    "source": source.text,
                    "sources": dict(source.imports),
                },
                root,
            )
            return Model(self, response["model"], root, tuple(response["queries"]))

    def _load(self, path: Path, source: str | None = None) -> Model:
        root = self._data_root or path.parent
        response = self._request(
            {"op": "load", "url": path.as_uri(), "source": source}, root
        )
        return Model(self, response["model"], root, tuple(response["queries"]))

    def run(
        self,
        source: str,
        *,
        query: str | None = None,
        givens: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> pl.DataFrame:
        """Execute inline Malloy and return a materialized Polars dataframe.

        Defaults to the final run statement. `query` selects a named query,
        exported source view, or run identifier. Temporary models are released.
        """
        if not isinstance(source, str):
            raise TypeError("source must be Malloy text. Use load(path) for files.")
        if query is not None and not isinstance(query, str):
            raise TypeError("query must be a string or None")
        values = encode_givens(givens)
        base = self._data_root or Path.cwd()
        with self._operation(timeout):
            model = self._load(base / "inline.malloy", source)
            try:
                return model._execute(None, query, values)
            finally:
                if not self._bridge.terminated:
                    self._request(
                        {"op": "release", "model": model._handle}, model._data_root
                    )
                model._owner = None


class Model:
    """A reusable Malloy model and its schema snapshot, owned by a Session."""

    def __init__(
        self, session: Session, handle: int, data_root: Path, queries: tuple[str, ...]
    ) -> None:
        self._owner: Session | None = session
        self._handle = handle
        self._data_root = data_root
        self._queries = queries

    @property
    def _session(self) -> Session:
        if self._owner is None:
            raise SessionError("Model is closed. Load or create a new model.")
        return self._owner

    @property
    def queries(self) -> tuple[str, ...]:
        """Available named queries, exported source views, and run/SQL identifiers."""
        return self._queries

    def _check_open(self) -> None:
        self._session._check_open()

    def run(
        self,
        source: str | None = None,
        *,
        query: str | None = None,
        givens: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> pl.DataFrame:
        """Run a Malloy query against this model and return a Polars dataframe.

        Pass full query source such as `run: orders -> by_region`, or select
        `query='orders.by_region'`. With neither, execute the final run statement.
        Givens are bound by Malloy for this call. Existing model defaults persist.
        """
        if source is not None and query is not None:
            raise ValueError("Pass source or query, not both")
        if source is not None and not isinstance(source, str):
            raise TypeError("source must be Malloy text")
        if query is not None and not isinstance(query, str):
            raise TypeError("query must be a string or None")
        values = encode_givens(givens)
        session = self._session
        with session._operation(timeout):
            return self._execute(source, query, values)

    def inspect(
        self,
        *,
        position: Position | None = None,
        url: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Return model schemas, givens, annotations, dependencies, and diagnostics.

        With `position`, include its reference and import target. `url` selects an
        imported document. Omitting it selects the model's root document.
        """
        if position is not None and not isinstance(position, Position):
            raise TypeError("position must be a Position")
        if url is not None and not isinstance(url, str):
            raise TypeError("url must be a string or None")
        if url is not None and position is None:
            raise ValueError("url requires a position")
        with self._session._operation(timeout):
            self._check_open()
            response = self._session._request(
                {
                    "op": "inspect",
                    "model": self._handle,
                    "position": {
                        "line": position.line,
                        "character": position.character,
                        "url": url,
                    }
                    if position
                    else None,
                },
                self._data_root,
            )
            return response["inspection"]

    def sql(
        self,
        source: str | None = None,
        *,
        query: str | None = None,
        givens: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> str:
        """Compile a query to SQL with resolved data paths, without executing it."""
        if source is not None and query is not None:
            raise ValueError("Pass source or query, not both")
        if source is not None and not isinstance(source, str):
            raise TypeError("source must be Malloy text")
        if query is not None and not isinstance(query, str):
            raise TypeError("query must be a string or None")
        values = encode_givens(givens)
        with self._session._operation(timeout):
            return self._sql(source, query, values)

    def _execute(
        self, source: str | None, query: str | None, values: dict[str, Any]
    ) -> pl.DataFrame:
        sql = self._sql(source, query, values)
        relation = self._session.connection.sql(sql)
        return pl.DataFrame(relation) if relation is not None else pl.DataFrame()

    def _sql(
        self, source: str | None, query: str | None, values: dict[str, Any]
    ) -> str:
        self._check_open()
        session = self._session
        response = session._request(
            {
                "op": "query",
                "model": self._handle,
                "source": source,
                "query": query,
                "givens": values,
            },
            self._data_root,
        )
        return session._data.bind(
            response["sql"], data_root=self._data_root, allow_write=True
        ).sql

    def close(self) -> None:
        """Release the model's state in Deno."""
        session = self._owner
        if session is None:
            return
        with session._lock:
            if self._owner is not None:
                try:
                    if not session.closed:
                        with session._operation():
                            session._request(
                                {"op": "release", "model": self._handle},
                                self._data_root,
                            )
                finally:
                    self._owner = None

    def __enter__(self) -> Self:
        self._check_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
