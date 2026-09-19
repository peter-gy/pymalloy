from __future__ import annotations

import json
import math
import threading
import time
import weakref
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Self

import duckdb

from pymalloy._authoring.draft import Draft
from pymalloy._authoring.syntax import Fragment
from pymalloy._model import DEFAULT_CONNECTION
from pymalloy._model.errors import ModelError
from pymalloy._model.inputs import DataInput
from pymalloy._model.selection import query_names
from pymalloy._model.source import (
    DocumentKind,
    ModelSource,
    resolve_document_kind,
    resolve_source,
)
from pymalloy._notebook import NotebookDisplay
from pymalloy._protocol.givens import encode_givens, given_values
from pymalloy._protocol.records import (
    CheckReady,
    DocumentCell,
    DocumentReady,
    InspectionReady,
    ModelReady,
    QueryReady,
    SourceReady,
)
from pymalloy.analysis import (
    CheckReport,
    Inspection,
    QueryDescriptor,
    SourcePosition,
)
from pymalloy.execution import ExecutionContext, ExecutionError
from pymalloy.result import Result

from .compiler import Compiler
from .deadline import interrupt_at
from .engine import Engine


def _close(compiler: Compiler | None, engine: Engine) -> None:
    try:
        if compiler is not None:
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
        config: Mapping[str, Any] | None = None,
        extensions: Sequence[str] = (),
        connection_name: str = DEFAULT_CONNECTION,
        read_only: bool = False,
        timeout: float = 120,
        compiler_memory_mb: int = 256,
        deadline: float | None = None,
        compiler: Compiler | None = None,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Model timeout must be finite and positive")
        if not isinstance(connection_name, str) or not connection_name:
            raise ValueError("connection_name must be a nonempty string")
        self._connection = {"name": connection_name, "dialect": "duckdb"}
        deadline = deadline if deadline is not None else time.monotonic() + timeout
        self._engine = Engine(
            data_root=data_root,
            database=database,
            connection=connection,
            config=config,
            extensions=extensions,
            read_only=read_only,
            deadline=deadline,
        )
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Model startup exceeded its deadline")
            self._compiler = compiler or Compiler(
                memory_mb=compiler_memory_mb, timeout=remaining
            )
        except BaseException:
            self._engine.close()
            raise
        self.timeout = timeout
        self._root = Path(data_root or Path.cwd()).resolve()
        self._lock = threading.RLock()
        self._closed = False
        self._cleanup = weakref.finalize(
            self, _close, self._compiler if compiler is None else None, self._engine
        )

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
            try:
                with interrupt_at(
                    self.connection,
                    deadline,
                    message=f"Malloy operation exceeded {budget:g} seconds",
                ):
                    yield deadline
            except (KeyboardInterrupt, SystemExit, ModelError):
                self.close()
                raise
            finally:
                if self._compiler.closed:
                    self.close()
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
        source: str | Path | ModelSource | Draft,
        *,
        url: str | None = None,
        document_kind: DocumentKind | None = None,
        deadline: float,
    ) -> Model:
        """Compile text, a Path, or a closed ModelSource snapshot."""
        if document_kind is None and isinstance(source, (Draft, ModelSource)):
            document_kind = source.document_kind
        inputs = source.inputs if isinstance(source, Draft) else ()
        if isinstance(source, Draft):
            url = url or source.url
            source = source._input()
        identity, text, imports = resolve_source(source, url=url, root=self._root)
        with self.operation(deadline=deadline):
            result = self.request(
                {
                    "op": "begin",
                    "url": identity,
                    "source": text,
                    "connection": self._connection,
                    "documentKind": resolve_document_kind(identity, document_kind),
                },
                ModelReady,
                deadline=deadline,
                imports=imports,
            )
            return Model(
                self,
                tuple(result.queries),
                imports,
                ModelSource(
                    result.source.url,
                    result.source.text,
                    result.source.imports,
                    result.source.document_kind,
                ),
                result.compiler_version,
                inputs,
            )

    def check(
        self,
        source: str | Path | ModelSource | Draft,
        *,
        path: str | Path | None = None,
        url: str | None = None,
        document_kind: DocumentKind | None = None,
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
        if document_kind is None and isinstance(source, (Draft, ModelSource)):
            document_kind = source.document_kind
        if isinstance(source, Draft):
            url = url or source.url
            source = source._input()
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
            "connection": self._connection,
            "documentKind": resolve_document_kind(identity, document_kind),
        }
        if position is not None:
            request["position"] = {
                "line": position.line,
                "character": position.character,
            }
        with self.operation(deadline=deadline):
            return self.request(
                request, CheckReady, deadline=deadline, imports=imports
            ).report

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._cleanup()


class Model(NotebookDisplay):
    """A compiled model with retained source, schemas and query inventory.

    Create with model or Draft.compile. Reuse queries to execute against current
    data. Recompile after source/schema changes. Explicit close releases owned
    resources promptly, and optional context management is also supported.

    Attributes
    ----------
    queries : sequence of QueryDescriptor
        Available names, kinds and authored locations. Pass a name to query.
    compiler_version : str
        Malloy compiler version used to compile the model.
    connection : duckdb.DuckDBPyConnection
        The native data connection. A borrowed connection remains caller-owned.
    closed : bool
        Whether this model is closed and cannot accept more work.

    Examples
    --------
    >>> import pymalloy as pm
    >>> model = pm.model("query: answer is duckdb.sql('SELECT 42 AS n') -> {select: n}")
    >>> [q.name for q in model.queries]
    ['answer']
    >>> model.query("answer").run().rows()
    [{'n': 42}]
    >>> model.close()
    """

    def __init__(
        self,
        runtime: _Runtime,
        queries: tuple[QueryDescriptor, ...],
        imports: Mapping[str, str] | None,
        source: ModelSource,
        compiler_version: str,
        inputs: tuple[DataInput, ...],
    ) -> None:
        self._inputs = inputs
        self._source = source
        self.compiler_version = compiler_version
        self._owner = runtime
        self.queries = queries
        self._imports = imports

    def _notebook_subject(self):
        from pymalloy._notebook.subject import native

        return native(
            self._source,
            kind="Compiled model",
            queries=self.queries,
            inspect=self.inspect,
            preview=lambda selection, values: self.query(selection).preview(
                givens=values, timeout=30
            ),
            connection_name=self._owner._connection["name"],
        )

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

    def query(
        self, selection: str | Fragment | None = None, *, malloy: str | None = None
    ) -> Query:
        """Select a named query or extend this model with an ad hoc query.

        Parameters
        ----------
        selection : str or Fragment, optional
            A query inventory name, or a composed source/query expression. A string
            selects a name and is not interpreted as Malloy text. With None, choose
            the last run or the sole query. Otherwise an explicit selection is needed.
        malloy : str, optional
            Complete Malloy query text, such as ``run: orders -> { select: * }``.
            Mutually exclusive with selection. It can reference this model's sources.

        Returns
        -------
        Query
            A selection retaining this model. SQL is prepared and givens are bound
            when sql, run or preview is called.

        Examples
        --------
        >>> import pymalloy as pm
        >>> model = pm.model("source: values is duckdb.sql('SELECT 42 AS n')")
        >>> query = model.query(pm.ref("values").pipe(pm.query(pm.select(pm.col("n")))))
        >>> query.run().rows()
        [{'n': 42}]
        >>> model.close()
        """
        self._owner._check_open()
        if selection is not None and not isinstance(selection, (str, Fragment)):
            raise TypeError("Query selection must be a name or source/query fragment")
        if malloy is not None and not isinstance(malloy, str):
            raise TypeError("malloy must be query text")
        if selection is not None and malloy is not None:
            raise ValueError("Choose a query selection or Malloy text")
        inputs = selection.inputs if isinstance(selection, Fragment) else ()
        if isinstance(selection, Fragment):
            if selection.kind != "expression":
                raise TypeError("Query selection requires a source/query expression")
            malloy = "run: " + selection.render(materialize=True)
            selection = None
        if malloy is not None:
            return Query(
                self,
                QueryDescriptor(name="query", kind="run", location=None),
                {"malloy": malloy},
                inputs,
            )
        name = selection
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
        """Capture the model's source text and resolved imports.

        Parameters
        ----------
        timeout : float, optional
            Deadline in seconds. None uses the model's default operation budget.

        Returns
        -------
        ModelSource
            Detached source snapshot usable after model closure. Table data and
            captured Python data owners are not included. Use bundle for data files.

        Examples
        --------
        >>> import pymalloy as pm
        >>> text = "run: duckdb.sql('SELECT 42 AS n') -> {select: n}"
        >>> model = pm.model(text)
        >>> captured = model.source()
        >>> model.close()
        >>> pm.run(captured).rows()
        [{'n': 42}]
        """
        source = self._request({"op": "source"}, SourceReady, timeout).source
        return ModelSource(
            source.url, source.text, source.imports, source.document_kind
        )

    def inspect(
        self,
        *,
        position: SourcePosition | None = None,
        url: str | None = None,
        timeout: float | None = None,
    ) -> Inspection:
        """Inspect schemas, annotations, dependencies, givens and source references.

        Parameters
        ----------
        position : SourcePosition, optional
            Zero-based line and code-point character for a reference lookup.
        url : str, optional
            Imported source URL for that lookup. Requires position.
        timeout : float, optional
            Deadline in seconds, defaulting to the model's operation budget.

        Returns
        -------
        Inspection
            Detached metadata. Source schemas and query outputs are distinct entries.
            Use pymalloy.analysis.to_dict for mutable Python containers.

        Examples
        --------
        >>> import pymalloy as pm
        >>> model = pm.model("source: values is duckdb.sql('SELECT 42 AS n')")
        >>> [s.name for s in model.inspect().model.sources]
        ['values']
        >>> model.close()
        """
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
        """Prepare ordered Markdown and query cells for inspection or export.

        Parameters
        ----------
        queries : sequence of str, optional
            Query names in requested order. None uses document defaults. An empty
            sequence selects no query cells while retaining Markdown/source inventory.
        all : bool, default False
            Select all available queries. Mutually exclusive with queries.
        givens : mapping, optional
            Values bound when preparing query SQL.
        timeout : float, optional
            Operation deadline in seconds, otherwise the model's default.

        Returns
        -------
        tuple of DocumentCell
            Ordered cells with authored text and prepared SQL. Queries are not executed.
            Use pymalloy.export.prepare for a format-ready notebook Document.

        Examples
        --------
        >>> import pymalloy as pm
        >>> model = pm.model("run: duckdb.sql('SELECT 42 AS n') -> {select: n}")
        >>> [cell.name for cell in model.document()]
        ['run:0']
        >>> model.close()
        """
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
        """Return the native DuckDB connection while this model is open.

        A borrowed connection and its transactions remain caller-owned. Changing
        schemas requires recompilation. Access after model closure raises ModelError.
        """
        self._owner._check_open()
        return self._owner.connection

    @property
    def closed(self) -> bool:
        """Return whether this model has closed or suffered a terminal runtime failure."""
        return self._owner.closed

    def sql(
        self, *, givens: Mapping[str, Any] | None = None, timeout: float | None = None
    ) -> str:
        """Prepare SQL for the default query without executing it.

        Parameters
        ----------
        givens : mapping, optional
            Values bound for this call's declared parameters.
        timeout : float, optional
            Operation deadline in seconds. None uses the model's default.

        Returns
        -------
        str
            The result of ``model.query().sql(...)``. Use query(name) when
            the model has several named queries and no default run.

        Examples
        --------
        >>> import pymalloy as pm
        >>> model = pm.model("run: duckdb.sql('SELECT 42 AS n') -> {select: n}")
        >>> isinstance(model.sql(), str)
        True
        >>> model.close()
        """
        return self.query().sql(givens=givens, timeout=timeout)

    def run(
        self, *, givens: Mapping[str, Any] | None = None, timeout: float | None = None
    ) -> Result:
        """Execute the default query against current data.

        Parameters
        ----------
        givens : mapping, optional
            Values bound for this call's declared parameters.
        timeout : float, optional
            Operation deadline in seconds. None uses the model's default.

        Returns
        -------
        Result
            The result of ``model.query().run(...)``. Use query(name) when
            the model has several named queries and no default run.

        Examples
        --------
        >>> import pymalloy as pm
        >>> model = pm.model("run: duckdb.sql('SELECT 42 AS n') -> {select: n}")
        >>> model.run().rows()
        [{'n': 42}]
        >>> model.close()
        """
        return self.query().run(givens=givens, timeout=timeout)

    def __enter__(self) -> Self:
        self._owner._check_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Release the compiler and owned connection, invalidating retained queries.

        Repeated calls are safe. Borrowed connections remain open. Already materialized
        Result objects retain their data after closure.

        Examples
        --------
        >>> import pymalloy as pm
        >>> model = pm.model("run: duckdb.sql('SELECT 42 AS n') -> {select: n}")
        >>> result = model.run()
        >>> model.close()
        >>> result.rows()
        [{'n': 42}]
        """
        self._owner.close()


class Query(NotebookDisplay):
    """A selection that retains its model and binds parameters separately per call.

    Obtain one from Model.query. Selecting does not execute SQL. The same Query
    can run repeatedly against current data with different givens.

    Attributes
    ----------
    name : str
        Inventory name, or "query" for an ad hoc selection.
    kind : str
        run, named, view or sql.
    location : SourceLocation or None
        Authored source location when available.

    See Also
    --------
    Model.query, Query.sql, Query.run, Query.preview

    Examples
    --------
    >>> import pymalloy as pm
    >>> model = pm.model("query: answer is duckdb.sql('SELECT 42 AS n') -> {select: n}")
    >>> query = model.query("answer")
    >>> query.name
    'answer'
    >>> query.run().rows()
    [{'n': 42}]
    >>> model.close()
    """

    def __init__(
        self,
        model: Model,
        info: QueryDescriptor,
        selection: str | dict[str, str],
        inputs: tuple[DataInput, ...] = (),
    ) -> None:
        self._model = model
        self._inputs = (*model._inputs, *inputs)
        self._selection = selection
        self.name, self.kind, self.location = info.name, info.kind, info.location
        self._info = info

    def _notebook_subject(self):
        from msgspec.structs import replace

        from pymalloy._notebook.subject import native

        model = self._model
        subject = native(
            model._source,
            kind=f"Query · {self.name}",
            queries=(self._info,),
            inspect=model.inspect,
            preview=lambda _selection, values: self.preview(givens=values, timeout=30),
            connection_name=model._owner._connection["name"],
        )
        if isinstance(self._selection, dict):
            subject.info = replace(subject.info, source=self._selection["malloy"])
        return subject

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
        """Prepare SQL with this call's given values.

        Parameters
        ----------
        givens : mapping, optional
            Typed values for declared Malloy parameters. Omitted values use declared
            defaults. Bindings are scoped to this call and not stored on the Query.
        timeout : float, optional
            Positive seconds for waiting, SQL preparation and execution as applicable.
            None uses the parent model's default budget.

        Returns
        -------
        str
            SQL text generated by Malloy.

        Notes
        -----
        Does not execute the result query. Preparing ad hoc source may discover schemas.

        Examples
        --------
        >>> import pymalloy as pm
        >>> model = pm.model("run: duckdb.sql('SELECT 42 AS n') -> {select: n}")
        >>> isinstance(model.query().sql(), str)
        True
        >>> model.close()
        """
        with self._model._owner.operation(timeout) as deadline:
            return self._sql(givens, deadline)

    def _execute(
        self, givens: Mapping[str, Any] | None, timeout: float | None, limit: int | None
    ) -> Result:
        runtime = self._model._owner
        # Freeze the bindings before compilation, so caller mutation cannot change evidence.
        encoded = encode_givens(givens)
        with runtime.operation(timeout) as deadline:
            sql = self._sql(given_values(encoded), deadline)
            if time.monotonic() >= deadline:
                raise TimeoutError("Query execution exceeded its deadline")
            try:
                return (
                    runtime._engine.run(sql)
                    if limit is None
                    else runtime._engine.preview(sql, limit)
                )
            except duckdb.Error as error:
                context = ExecutionContext(
                    source=ModelSource(
                        self._model._source.url,
                        self._model._source.text,
                        {**self._model._source.imports, **runtime._compiler.sources},
                        self._model._source.document_kind,
                    ),
                    query=self._info,
                    malloy=self._selection.get("malloy")
                    if isinstance(self._selection, dict)
                    else None,
                    sql=sql,
                    compiler_version=self._model.compiler_version,
                    connection_name=runtime._connection["name"],
                    preview_limit=limit,
                    _givens_json=json.dumps(encoded),
                    _inputs=self._inputs,
                )
                raise ExecutionError(context, error) from error

    def run(
        self, *, givens: Mapping[str, Any] | None = None, timeout: float | None = None
    ) -> Result:
        """Execute this selection and materialize its result.

        Parameters
        ----------
        givens : mapping, optional
            Typed values for declared Malloy parameters. Omitted values use declared
            defaults. Bindings are scoped to this call and not stored on the Query.
        timeout : float, optional
            Positive seconds for waiting, SQL preparation and execution as applicable.
            None uses the parent model's default budget.

        Returns
        -------
        Result
            Materialized Arrow-backed values, native columns and executed SQL.

        Notes
        -----
        Reads current data. DuckDB errors raise ExecutionError with detached replay context.

        Examples
        --------
        >>> import pymalloy as pm
        >>> model = pm.model("run: duckdb.sql('SELECT 42 AS n') -> {select: n}")
        >>> model.query().run().rows()
        [{'n': 42}]
        >>> model.close()
        """
        return self._execute(givens, timeout, None)

    def preview(
        self,
        *,
        limit: int = 20,
        givens: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Result:
        """Execute a SELECT with a bounded number of output rows.

        Parameters
        ----------
        limit : int, default 20
            Outer result limit, from 1 through 10,000. Booleans are rejected.
        givens : mapping, optional
            Values for this execution's declared parameters.
        timeout : float, optional
            Operation deadline in seconds, defaulting to the model's budget.

        Returns
        -------
        Result
            At most limit output rows. COPY is rejected before execution.

        Notes
        -----
        An outer limit does not bound aggregation/input-scanning cost. Set a timeout
        for exploratory queries. Add order_by when the preview needs a stable order.

        Examples
        --------
        >>> import pymalloy as pm
        >>> model = pm.model("run: duckdb.sql('SELECT range AS n FROM range(10)') -> {select: n order_by: n}")
        >>> model.query().preview(limit=2).rows()
        [{'n': 0}, {'n': 1}]
        >>> model.close()
        """
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError("Preview limit must be an integer from 1 to 10000")
        return self._execute(givens, timeout, limit)
