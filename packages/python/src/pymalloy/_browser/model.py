from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import msgspec

from pymalloy._model.inputs import Input
from pymalloy._model.source import ModelSource
from pymalloy._notebook import NotebookDisplay
from pymalloy._protocol.codec import decode_result
from pymalloy._protocol.givens import encode_givens
from pymalloy._protocol.records import Column
from pymalloy.analysis import Inspection, QueryDescriptor, SourcePosition
from pymalloy.authoring import Source
from pymalloy.errors import ClosedError

from .ffi import encode

if TYPE_CHECKING:
    from .connection import Connection


@dataclass(frozen=True)
class Result(NotebookDisplay):
    """Detached Malloy values with SQL and native column descriptions.

    Returned by browser Query.run and Query.preview. Exact integers, Decimal
    values, nested records, and arrays survive the browser/Python boundary.
    Data remains available after its model and connection close.
    """

    sql: str
    columns: tuple[Column, ...]
    _wire: bytes = field(repr=False)

    @classmethod
    def _create(cls, payload: str) -> Result:
        result = msgspec.json.decode(payload)
        decode_result(result["malloy"])
        return cls(
            result["sql"],
            msgspec.convert(result["columns"], tuple[Column, ...], strict=True),
            msgspec.json.encode(result["malloy"]),
        )

    def _malloy(self) -> dict[str, Any]:
        return msgspec.json.decode(self._wire)

    def _notebook_subject(self):
        from pymalloy._notebook.subject import materialized

        return materialized(self._malloy())

    def to_pylist(self) -> list[dict[str, Any]]:
        """Return detached rows with exact numbers and nested Python containers.

        Every call allocates fresh containers. Mutating them leaves the retained
        result unchanged. Dates and timestamps use the wire's ISO text values.
        """
        return decode_result(self._malloy())["rows"]


class Model(NotebookDisplay):
    """A compiled browser model with retained source and query inventory.

    Obtain with ``await connection.model(source)``. Queries retain their model.
    Closing a model aborts its pending operations and invalidates its queries.
    """

    _handle: Any

    def __init__(
        self,
        connection: Connection,
        handle: Any,
        *,
        inputs: tuple[Input, ...],
        timeout: float,
    ) -> None:
        self._connection = connection
        self._handle = handle
        self._closed = False
        self._inputs = inputs
        self._timeout = timeout
        self.queries = msgspec.json.decode(
            handle.queries(), type=tuple[QueryDescriptor, ...]
        )
        self.compiler_version = str(handle.compilerVersion)
        source = msgspec.json.decode(handle.source())
        self._source = ModelSource(
            source["url"],
            source["text"],
            source["imports"],
            source["documentKind"],
            inputs=inputs,
        )

    @property
    def closed(self) -> bool:
        """Return whether this model or its browser connection has closed."""
        return (
            self._closed
            or self._connection.closed
            or (self._handle is not None and bool(self._handle.closed))
        )

    def _check_open(self) -> None:
        if self.closed:
            raise ClosedError("Browser model is closed. Compile a new model.")

    def source(self) -> ModelSource:
        """Return the retained root text, resolved imports, and captured inputs."""
        return self._source

    def _notebook_subject(self):
        from pymalloy._notebook.subject import asynchronous

        return asynchronous(
            self._source,
            kind="Model",
            queries=self.queries,
            inspect=self.inspect,
            preview=lambda selection, values: self.query(selection).preview(
                givens=values
            ),
            connection_name=self._connection.name,
        )

    def query(
        self, selection: str | Source | None = None, *, malloy: str | None = None
    ) -> Query:
        """Select a query inventory name or compose an ad hoc source expression.

        None selects the last run or the sole available query. ``malloy`` takes
        complete Malloy query text and is mutually exclusive with selection.
        """
        self._check_open()
        if selection is not None and not isinstance(selection, (str, Source)):
            raise TypeError("Query selection must be a name or Source")
        if malloy is not None and not isinstance(malloy, str):
            raise TypeError("malloy must be query text")
        if selection is not None and malloy is not None:
            raise ValueError("Choose a query selection or Malloy text")
        inputs: tuple[Input, ...] = ()
        if isinstance(selection, Source):
            if selection.kind != "expression":
                raise TypeError("Query selection requires a source/query expression")
            inputs = selection.inputs
            owned = {value.reference for value in self._inputs}
            if any(value.reference not in owned for value in inputs):
                raise ValueError(
                    "Bind captured inputs to a Draft before compiling a browser model"
                )
            malloy = "run: " + selection.text
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
            runs = [query for query in self.queries if query.kind == "run"]
            name = (
                runs[-1].name
                if runs
                else self.queries[0].name
                if len(self.queries) == 1
                else None
            )
        info = next((query for query in self.queries if query.name == name), None)
        if info is None:
            available = ", ".join(query.name for query in self.queries)
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

    async def inspect(
        self,
        *,
        position: SourcePosition | None = None,
        url: str | None = None,
        timeout: float | None = None,
    ) -> Inspection:
        """Return detached schemas, annotations, dependencies, and givens.

        ``position`` uses zero-based line and Unicode code-point offsets.
        ``url`` selects an imported source and requires position.
        """
        self._check_open()
        if position is not None and not isinstance(position, SourcePosition):
            raise TypeError("position must be a SourcePosition")
        if url is not None and not isinstance(url, str):
            raise TypeError("url must be a string")
        if url is not None and position is None:
            raise ValueError("url requires a position")
        options = encode(
            {
                **(
                    {
                        "position": {
                            "line": position.line,
                            "character": position.character,
                        }
                    }
                    if position is not None
                    else {}
                ),
                **({"url": url} if url is not None else {}),
            }
        )

        async def inspect(_handle: Any, signal: Any) -> Inspection:
            return msgspec.json.decode(
                await self._handle.inspect(options, signal), type=Inspection
            )

        return await self._connection._call(
            inspect,
            timeout=self._timeout if timeout is None else timeout,
            owner=self,
        )

    def close(self) -> None:
        """Abort this model's pending work and release its compiler state.

        Repeated calls are safe. The connection remains available. A subsequent
        connection operation waits for this model's aborted work to settle.
        """
        if not self._closed:
            self._closed = True
            for operation in tuple(self._connection._operations):
                if operation.owner is self:
                    operation.abort()
            try:
                if self._handle is not None:
                    self._handle.close()
            finally:
                self._handle = None
                self._connection._models.discard(self)


class Query(NotebookDisplay):
    """A browser query selection that retains its compiled model.

    Selecting a query executes no SQL. Each awaited execution binds its own
    givens and reads current data through the model's captured virtual files.
    """

    def __init__(
        self,
        model: Model,
        info: QueryDescriptor,
        selection: str | dict[str, str],
        inputs: tuple[Input, ...] = (),
    ) -> None:
        self._model = model
        self._info = info
        self._selection = selection
        self._inputs = (*model._inputs, *inputs)
        self.name, self.kind, self.location = info.name, info.kind, info.location

    def _notebook_subject(self):
        from msgspec.structs import replace

        from pymalloy._notebook.subject import asynchronous

        subject = asynchronous(
            self._model._source,
            kind="Query" if self.kind == "run" else f"Query · {self.name}",
            queries=(self._info,),
            inspect=self._model.inspect,
            preview=lambda _selection, values: self.preview(givens=values),
            connection_name=self._model._connection.name,
        )
        if isinstance(self._selection, dict):
            subject.info = replace(subject.info, source=self._selection["malloy"])
        return subject

    async def sql(
        self, *, givens: Mapping[str, Any] | None = None, timeout: float | None = None
    ) -> str:
        """Prepare SQL with this call's given values, discovering schemas as needed."""
        self._model._check_open()
        selected = encode(self._selection)
        values = encode(encode_givens(givens))

        async def sql(_handle: Any, signal: Any) -> str:
            query = self._model._handle.query(selected)
            return await query.sql(values, signal)

        return await self._model._connection._call(
            sql,
            timeout=self._model._timeout if timeout is None else timeout,
            owner=self._model,
        )

    async def _execute(
        self,
        *,
        givens: Mapping[str, Any] | None,
        timeout: float | None,
        limit: int | None,
    ) -> Result:
        self._model._check_open()
        selected = encode(self._selection)
        values = encode(encode_givens(givens))

        async def execute(_handle: Any, signal: Any) -> Result:
            query = self._model._handle.query(selected)
            payload = (
                await query.run(values, signal)
                if limit is None
                else await query.preview(limit, values, signal)
            )
            return Result._create(payload)

        return await self._model._connection._call(
            execute,
            timeout=self._model._timeout if timeout is None else timeout,
            owner=self._model,
        )

    async def run(
        self, *, givens: Mapping[str, Any] | None = None, timeout: float | None = None
    ) -> Result:
        """Execute this selection and return detached Python-readable Malloy values."""
        return await self._execute(givens=givens, timeout=timeout, limit=None)

    async def preview(
        self,
        *,
        limit: int = 20,
        givens: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Result:
        """Execute a SELECT with an outer limit from 1 through 10,000 rows.

        An outer limit bounds output, not aggregation or input-scanning cost.
        Use timeout to bound the whole operation, including waiting in the queue.
        """
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError("Preview limit must be an integer from 1 to 10000")
        return await self._execute(givens=givens, timeout=timeout, limit=limit)
