from __future__ import annotations

import math
import time
import weakref
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

import duckdb
import msgspec

from pymalloy._authoring.draft import Draft
from pymalloy._model.inputs import Input
from pymalloy._model.selection import query_names
from pymalloy._model.source import (
    DocumentKind,
    ModelSource,
    open_source,
)
from pymalloy._notebook import NotebookDisplay
from pymalloy._protocol.givens import encode_givens
from pymalloy._protocol.records import (
    BeginRequest,
    CheckReady,
    CheckRequest,
    DocumentCell,
    DocumentReady,
    DocumentRequest,
    Given,
    InspectionPosition,
    InspectionReady,
    InspectRequest,
    MalloyQuery,
    ModelReady,
    QueryReady,
    QueryRequest,
    QuerySelection,
    Request,
)
from pymalloy._protocol.records import (
    Connection as ConnectionRecord,
)
from pymalloy.analysis import (
    CheckReport,
    Inspection,
    QueryDescriptor,
    SourcePosition,
)
from pymalloy.authoring import Source
from pymalloy.errors import ClosedError, CompilerError, ExecutionContext, ExecutionError
from pymalloy.result import Result

from .compiler import Compiler
from .deadline import interrupt_at

if TYPE_CHECKING:
    from .api import Connection


def deadline_after(timeout: float) -> float:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Operation timeout must be finite and positive")
    return time.monotonic() + timeout


def remaining(deadline: float) -> float:
    budget = deadline - time.monotonic()
    if budget <= 0:
        raise TimeoutError("Malloy operation exceeded its deadline")
    return budget


class _Runtime:
    """Own one model's compiler and borrow its connection's engine and lock."""

    def __init__(
        self,
        owner: Connection,
        *,
        timeout: float,
        deadline: float,
        compiler: Compiler | None = None,
        own_compiler: bool = True,
    ) -> None:
        self._owner = owner
        self._connection = ConnectionRecord(name=owner.name, dialect="duckdb")
        self._engine = owner._engine
        self._compiler = compiler or Compiler(
            memory_mb=owner._compiler_memory_mb, timeout=remaining(deadline)
        )
        self.timeout = timeout
        self._root = owner._root
        self._lock = owner._lock
        self._closed = False
        self._cleanup = (
            weakref.finalize(self, self._compiler.close) if own_compiler else None
        )
        if own_compiler:
            owner._runtimes.add(self)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        return self._engine.connection

    @property
    def closed(self) -> bool:
        return self._closed

    def _check_open(self) -> None:
        if self._closed:
            raise ClosedError("Model is closed. Create a new model.")

    @contextmanager
    def operation(self, *, deadline: float) -> Generator[float, None, None]:
        if not self._lock.acquire(timeout=remaining(deadline)):
            raise TimeoutError("Waiting for the connection exceeded its deadline")
        try:
            remaining(deadline)
            self._owner._check_open()
            self._check_open()
            try:
                with interrupt_at(
                    self.connection,
                    deadline,
                    message="Malloy operation exceeded its deadline",
                ):
                    yield deadline
            except (KeyboardInterrupt, SystemExit, ClosedError, CompilerError):
                self.close()
                raise
            finally:
                if self._compiler.closed:
                    self.close()
        finally:
            self._lock.release()

    def request[T](
        self,
        request: Request,
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
        logical = source.text if isinstance(source, (Draft, ModelSource)) else None
        inputs = source.inputs if isinstance(source, (Draft, ModelSource)) else ()
        with self.operation(deadline=deadline):
            identity, text, imports, kind = open_source(
                source,
                url=url,
                document_kind=document_kind,
                root=self._root,
                materialize=True,
                parse=lambda text, url, kind: self._compiler.parse(
                    text, url=url, document_kind=kind, deadline=deadline
                ),
            )
            result = self.request(
                BeginRequest(
                    url=identity,
                    source=text,
                    connection=self._connection,
                    document_kind=kind,
                ),
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
                    logical if logical is not None else result.source.text,
                    source.imports
                    if isinstance(source, ModelSource)
                    else result.source.imports,
                    result.source.document_kind,
                    inputs=inputs,
                ),
                result.compiler_version,
                inputs,
            )

    def check(
        self,
        source: str | Path | ModelSource | Draft,
        *,
        url: str | None = None,
        document_kind: DocumentKind | None = None,
        position: SourcePosition | None = None,
        deadline: float,
    ) -> CheckReport:
        if position is not None and not isinstance(position, SourcePosition):
            raise TypeError("position must be a SourcePosition")
        with self.operation(deadline=deadline):
            identity, text, imports, kind = open_source(
                source,
                url=url,
                document_kind=document_kind,
                root=self._root,
                materialize=True,
                parse=lambda text, url, kind: self._compiler.parse(
                    text, url=url, document_kind=kind, deadline=deadline
                ),
            )
            request = CheckRequest(
                source=text,
                url=identity,
                connection=self._connection,
                document_kind=kind,
                position=position if position is not None else msgspec.UNSET,
            )
            return self.request(
                request, CheckReady, deadline=deadline, imports=imports
            ).report

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                if self._cleanup is not None:
                    self._cleanup()


class Model(NotebookDisplay):
    """A compiled model with retained source, schemas and query inventory.

    Create with Connection.model. Reuse queries to execute against current
    data. Recompile after source/schema changes. Explicit close releases owned
    resources promptly, and optional context management is also supported.

    Attributes
    ----------
    queries : sequence of QueryDescriptor
        Available names, kinds and authored locations. Pass a name to query.
    compiler_version : str
        Malloy compiler version used to compile the model.
    closed : bool
        Whether this model is closed and cannot accept more work.

    Examples
    --------
    >>> import pymalloy as pm
    >>> model = pm.connect().model("query: answer is duckdb.sql('SELECT 42 AS n') -> {select: n}")
    >>> [q.name for q in model.queries]
    ['answer']
    >>> model.query("answer").run().to_pylist()
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
        inputs: tuple[Input, ...],
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
            kind="Model",
            queries=self.queries,
            inspect=self.inspect,
            preview=lambda selection, values: self.query(selection).preview(
                givens=values
            ),
            connection_name=self._owner._connection.name,
        )

    def _request_at[T](
        self, request: Request, response_type: type[T], deadline: float
    ) -> T:
        with self._owner.operation(deadline=deadline):
            return self._owner.request(
                request, response_type, deadline=deadline, imports=self._imports
            )

    def query(
        self, selection: str | Source | None = None, *, malloy: str | None = None
    ) -> Query:
        """Select a named query or extend this model with an ad hoc query.

        Parameters
        ----------
        selection : str or Source, optional
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
        >>> model = pm.connect().model("source: values is duckdb.sql('SELECT 42 AS n')")
        >>> query = model.query(pm.source("values").pipe(pm.view().select(pm.col("n"))))
        >>> query.run().to_pylist()
        [{'n': 42}]
        >>> model.close()
        """
        self._owner._check_open()
        if selection is not None and not isinstance(selection, (str, Source)):
            raise TypeError("Query selection must be a name or Source")
        if malloy is not None and not isinstance(malloy, str):
            raise TypeError("malloy must be query text")
        if selection is not None and malloy is not None:
            raise ValueError("Choose a query selection or Malloy text")
        inputs = selection.inputs if isinstance(selection, Source) else ()
        if isinstance(selection, Source):
            if selection.kind != "expression":
                raise TypeError("Query selection requires a source/query expression")
            malloy = "run: " + selection.render(materialize=True)
            selection = None
        if malloy is not None:
            return Query(
                self,
                QueryDescriptor(name="query", kind="run", location=None),
                MalloyQuery(malloy=malloy),
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
            available = ", ".join(q.name for q in self.queries)
            if not available:
                raise ValueError(
                    "This model has no queries. Bind one with Draft.queries "
                    "or pass malloy= query text."
                )
            if name is None:
                raise ValueError(
                    f"This model has several queries. Choose one of: {available}"
                )
            raise ValueError(f"Unknown query {name!r}. Choose one of: {available}")
        return Query(self, info, info.name)

    def source(self) -> ModelSource:
        """Return logical root text and resolved imports retained at compilation."""
        return self._source

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
        >>> model = pm.connect().model("source: values is duckdb.sql('SELECT 42 AS n')")
        >>> [s.name for s in model.inspect().model.sources]
        ['values']
        >>> model.close()
        """
        return self._inspect(
            position=position,
            url=url,
            deadline=deadline_after(
                self._owner.timeout if timeout is None else timeout
            ),
        )

    def _inspect(self, *, position=None, url=None, deadline: float) -> Inspection:
        if position is not None and not isinstance(position, SourcePosition):
            raise TypeError("position must be a SourcePosition")
        if url is not None and not isinstance(url, str):
            raise TypeError("url must be a string")
        if url is not None and position is None:
            raise ValueError("url requires a position")
        request = InspectRequest(
            position=InspectionPosition(
                line=position.line,
                character=position.character,
                url=url if url is not None else msgspec.UNSET,
            )
            if position is not None
            else msgspec.UNSET
        )
        return self._request_at(request, InspectionReady, deadline).inspection

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
        >>> model = pm.connect().model("run: duckdb.sql('SELECT 42 AS n') -> {select: n}")
        >>> [cell.name for cell in model.document()]
        ['run:0']
        >>> model.close()
        """
        return self._document(
            queries=queries,
            all=all,
            givens=givens,
            deadline=deadline_after(
                self._owner.timeout if timeout is None else timeout
            ),
        )

    def _document(
        self, *, queries=None, all=False, givens=None, deadline: float
    ) -> tuple[DocumentCell, ...]:
        names = query_names(queries, all=all)
        request = DocumentRequest(
            all=all,
            givens=encode_givens(givens),
            queries=names if names is not None else msgspec.UNSET,
        )
        return tuple(self._request_at(request, DocumentReady, deadline).cells)

    @property
    def closed(self) -> bool:
        """Return whether this model has closed or its compiler has failed."""
        return self._owner.closed

    def __enter__(self) -> Self:
        self._owner._check_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Release this model's compiler, invalidating retained queries.

        Repeated calls are safe. The parent connection remains open. Materialized
        Result objects retain their data after closure.

        Examples
        --------
        >>> import pymalloy as pm
        >>> model = pm.connect().model("run: duckdb.sql('SELECT 42 AS n') -> {select: n}")
        >>> result = model.query().run()
        >>> model.close()
        >>> result.to_pylist()
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
    >>> model = pm.connect().model("query: answer is duckdb.sql('SELECT 42 AS n') -> {select: n}")
    >>> query = model.query("answer")
    >>> query.name
    'answer'
    >>> query.run().to_pylist()
    [{'n': 42}]
    >>> model.close()
    """

    def __init__(
        self,
        model: Model,
        info: QueryDescriptor,
        selection: QuerySelection,
        inputs: tuple[Input, ...] = (),
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
            kind="Query" if self.kind == "run" else f"Query · {self.name}",
            queries=(self._info,),
            inspect=model.inspect,
            preview=lambda _selection, values: self.preview(givens=values),
            connection_name=model._owner._connection.name,
        )
        if isinstance(self._selection, MalloyQuery):
            subject.info = replace(subject.info, source=self._selection.malloy)
        return subject

    def _sql(self, givens: Mapping[str, Given], deadline: float) -> str:
        return self._model._owner.request(
            QueryRequest(
                selection=self._selection,
                givens=givens,
            ),
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
        >>> model = pm.connect().model("run: duckdb.sql('SELECT 42 AS n') -> {select: n}")
        >>> isinstance(model.query().sql(), str)
        True
        >>> model.close()
        """
        with self._model._owner.operation(
            deadline=deadline_after(
                self._model._owner.timeout if timeout is None else timeout
            )
        ) as deadline:
            return self._sql(encode_givens(givens), deadline)

    def _execute(
        self, givens: Mapping[str, Any] | None, deadline: float, limit: int | None
    ) -> Result:
        runtime = self._model._owner
        # Freeze the bindings before compilation, so caller mutation cannot change evidence.
        encoded = encode_givens(givens)
        with runtime.operation(deadline=deadline):
            sql = self._sql(encoded, deadline)
            if time.monotonic() >= deadline:
                raise TimeoutError("Query execution exceeded its deadline")
            try:
                return (
                    runtime._engine.run(sql)
                    if limit is None
                    else runtime._engine.preview(sql, limit)
                )
            except duckdb.Error as error:
                if (
                    isinstance(error, duckdb.InterruptException)
                    and time.monotonic() >= deadline
                ):
                    raise TimeoutError(
                        "Query execution exceeded its deadline"
                    ) from error
                context = ExecutionContext._create(
                    source=ModelSource(
                        self._model._source.url,
                        self._model._source.text,
                        {**runtime._compiler.sources, **self._model._source.imports},
                        self._model._source.document_kind,
                        inputs=self._inputs,
                    ),
                    query=self._info,
                    malloy=self._selection.malloy
                    if isinstance(self._selection, MalloyQuery)
                    else None,
                    sql=sql,
                    compiler_version=self._model.compiler_version,
                    connection_name=runtime._connection.name,
                    preview_limit=limit,
                    _givens_json=msgspec.json.encode(encoded).decode(),
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
        >>> model = pm.connect().model("run: duckdb.sql('SELECT 42 AS n') -> {select: n}")
        >>> model.query().run().to_pylist()
        [{'n': 42}]
        >>> model.close()
        """
        return self._execute(
            givens,
            deadline_after(self._model._owner.timeout if timeout is None else timeout),
            None,
        )

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
        >>> model = pm.connect().model("run: duckdb.sql('SELECT range AS n FROM range(10)') -> {select: n order_by: n}")
        >>> model.query().preview(limit=2).to_pylist()
        [{'n': 0}, {'n': 1}]
        >>> model.close()
        """
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError("Preview limit must be an integer from 1 to 10000")
        return self._execute(
            givens,
            deadline_after(self._model._owner.timeout if timeout is None else timeout),
            limit,
        )
