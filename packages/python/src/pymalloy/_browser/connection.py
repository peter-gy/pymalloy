from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self
from urllib.parse import urlsplit

import msgspec

from pymalloy._authoring.draft import Draft
from pymalloy._authoring.syntax import Syntax, from_wire
from pymalloy._model import DEFAULT_CONNECTION
from pymalloy._model.inputs import Input
from pymalloy._model.source import DocumentKind, ModelSource, open_source
from pymalloy._protocol.records import SyntaxNode
from pymalloy.analysis import CheckReport, ParseReport, SourcePosition
from pymalloy.errors import ClosedError

from .ffi import budget, controller, domain_error, encode, factory, require_browser
from .model import Model

if TYPE_CHECKING:
    from pymalloy.browser import Runtime

type File = bytes | bytearray | memoryview | Path | str


def _files(
    values: Mapping[str, File] | None, inputs: tuple[Input, ...] = ()
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    if values is not None:
        if not isinstance(values, Mapping):
            raise TypeError(
                "files must map virtual paths to bytes, Paths, or HTTP URLs"
            )
        for name, value in values.items():
            if not isinstance(name, str) or not name or "\0" in name:
                raise ValueError("File names must be nonempty strings")
            if isinstance(value, str):
                parsed = urlsplit(value)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise ValueError(f"File {name!r} requires an HTTP or HTTPS URL")
                result[name] = {"url": value}
            else:
                if isinstance(value, Path):
                    value = value.read_bytes()
                if not isinstance(value, (bytes, bytearray, memoryview)):
                    raise TypeError(
                        f"File {name!r} requires bytes, a Path, or an HTTP URL"
                    )
                result[name] = {
                    "base64": base64.b64encode(bytes(value)).decode("ascii")
                }
    for value in inputs:
        captured = {
            "base64": base64.b64encode(value._materialize().path.read_bytes()).decode(
                "ascii"
            )
        }
        if value.reference in result and result[value.reference] != captured:
            raise ValueError(
                f"File {value.reference!r} conflicts with a captured input"
            )
        result[value.reference] = captured
    return result


@dataclass(eq=False)
class _Operation:
    owner: Model | None
    task: asyncio.Task[Any] | None = None
    controller: Any = None

    def abort(self) -> None:
        if self.controller is not None:
            self.controller.abort()
        elif self.task is not None:
            self.task.cancel()


async def _settle(task: asyncio.Task[Any]) -> None:
    # JavaScript promises keep running when a Python waiter is cancelled.
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            if not task.done():
                raise
            break
    if not task.cancelled():
        task.exception()


class Connection:
    """Own a browser DuckDB worker and the lifetimes of compiled models.

    Use ``async with browser.connect() as connection``. Operations share one
    queue. Cancelling an operation aborts its JavaScript work and waits for it
    to settle before the next operation starts.
    """

    _timeout: float
    _name: str
    _options: str
    _closed: bool
    _handle: Any
    _lifetime: Any
    _lock: asyncio.Lock
    _operations: set[_Operation]
    _models: set[Model]
    _closing: asyncio.Task[None] | None

    def __new__(cls):
        raise TypeError("Create browser connections with browser.connect()")

    @classmethod
    def _create(cls, *, runtime: Runtime | None, name: str, timeout: float) -> Self:
        from pymalloy.browser import Runtime

        require_browser()
        if runtime is not None and not isinstance(runtime, Runtime):
            raise TypeError("runtime must be a browser.Runtime")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a nonempty string")
        self = object.__new__(cls)
        self._timeout = budget(timeout)
        self._name = name
        self._options = encode(
            {"name": name, **({"bundles": runtime._bundles()} if runtime else {})}
        )
        self._closed = False
        self._handle = None
        self._lifetime = None
        self._lock = asyncio.Lock()
        self._operations = set()
        self._models = set()
        self._closing = None
        return self

    @property
    def name(self) -> str:
        """Return the Malloy connection identifier."""
        return self._name

    @property
    def closed(self) -> bool:
        """Return whether this owner or its browser worker has closed."""
        return self._closed or (self._handle is not None and bool(self._handle.closed))

    def _check_open(self) -> None:
        if self.closed:
            raise ClosedError("Browser connection is closed. Create a new connection.")

    async def _call[T](
        self,
        invoke: Callable[[Any, Any], Awaitable[T]],
        *,
        timeout: float | None = None,
        owner: Model | None = None,
    ) -> T:
        self._check_open()
        seconds = budget(self._timeout if timeout is None else timeout)
        deadline = time.monotonic() + seconds
        operation = _Operation(owner)

        async def execute() -> T:
            async with self._lock:
                self._check_open()
                if owner is not None:
                    owner._check_open()
                operation.controller = controller()
                try:
                    if self._handle is None:
                        self._handle = await factory().open(
                            self._options, operation.controller.signal
                        )
                        self._lifetime = operation.controller
                        self._check_open()
                        operation.controller = controller()
                    return await invoke(self._handle, operation.controller.signal)
                except Exception as error:
                    if operation.controller.signal.aborted:
                        # An AbortController rejection is cancellation at the Python boundary.
                        raise asyncio.CancelledError from error
                    converted = domain_error(error)
                    if converted is error:
                        raise
                    raise converted from error
                finally:
                    operation.controller = None

        task = asyncio.create_task(execute())
        operation.task = task
        self._operations.add(operation)
        try:
            result = await asyncio.wait_for(asyncio.shield(task), seconds)
            if time.monotonic() >= deadline:
                raise TimeoutError("Browser operation exceeded its deadline")
            return result
        except (asyncio.CancelledError, TimeoutError):
            operation.abort()
            await _settle(task)
            raise
        finally:
            self._operations.discard(operation)

    async def model(
        self,
        source: str | Path | ModelSource | Draft,
        *,
        files: Mapping[str, File] | None = None,
        url: str | None = None,
        document_kind: DocumentKind | None = None,
        timeout: float | None = None,
    ) -> Model:
        """Compile source against an immutable snapshot of virtual files.

        File values are bytes, paths in Pyodide's filesystem, or HTTP(S) URLs.
        A string source is Malloy text. Pass a Path to read source from a file.
        Imported source must be present in files or the ModelSource snapshot.
        """
        self._check_open()
        identity, text, imports, kind = open_source(
            source, url=url, document_kind=document_kind, root=Path.cwd()
        )
        inputs = source.inputs if isinstance(source, (ModelSource, Draft)) else ()
        definition: dict[str, Any] = {
            "files": _files(files, inputs),
            "documentKind": kind,
        }
        if imports is None:
            definition.update(text=text, url=identity)
        else:
            definition["source"] = {
                "url": identity,
                "text": text,
                "imports": dict(imports),
                "documentKind": kind,
            }
        captured = encode(definition)
        seconds = budget(self._timeout if timeout is None else timeout)
        compiled: Model | None = None

        async def compile(handle: Any, signal: Any) -> Model:
            nonlocal compiled
            proxy = await handle.model(captured, signal)
            try:
                model = Model(self, proxy, inputs=inputs, timeout=seconds)
                self._models.add(model)
                compiled = model
                return model
            except BaseException:
                proxy.close()
                raise

        try:
            return await self._call(compile, timeout=seconds)
        except BaseException:
            if compiled is not None:
                compiled.close()
            raise

    async def check(
        self,
        source: str | Path | ModelSource | Draft,
        *,
        files: Mapping[str, File] | None = None,
        url: str | None = None,
        document_kind: DocumentKind | None = None,
        position: SourcePosition | None = None,
        timeout: float | None = None,
    ) -> CheckReport:
        """Check source, names, types, and file schemas in the browser runtime."""
        self._check_open()
        identity, text, imports, kind = open_source(
            source, url=url, document_kind=document_kind, root=Path.cwd()
        )
        inputs = source.inputs if isinstance(source, (ModelSource, Draft)) else ()
        selected_files = _files(files, inputs)
        if position is not None and not isinstance(position, SourcePosition):
            raise TypeError("position must be a SourcePosition")
        options = encode(
            {
                "url": identity,
                "documentKind": kind,
                "files": selected_files,
                **(
                    {
                        "source": {
                            "url": identity,
                            "text": text,
                            "imports": dict(imports),
                            "documentKind": kind,
                        }
                    }
                    if imports is not None
                    else {}
                ),
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
            }
        )

        async def check(handle: Any, signal: Any) -> CheckReport:
            return msgspec.json.decode(
                await handle.check(text, options, signal), type=CheckReport
            )

        return await self._call(check, timeout=timeout)

    async def parse(
        self,
        source: str | Path | ModelSource | Draft,
        *,
        url: str | None = None,
        document_kind: DocumentKind | None = None,
        timeout: float | None = None,
    ) -> ParseReport:
        """Parse source and return compiler diagnostics and authored locations."""
        self._check_open()
        identity, text, _, kind = open_source(
            source, url=url, document_kind=document_kind, root=Path.cwd()
        )
        options = encode({"url": identity, "documentKind": kind})

        async def parse(handle: Any, _signal: Any) -> ParseReport:
            return msgspec.json.decode(handle.parse(text, options), type=ParseReport)

        return await self._call(parse, timeout=timeout)

    async def format(self, source: str, *, timeout: float | None = None) -> str:
        """Format Malloy model text with the packaged compiler."""
        self._check_open()
        if not isinstance(source, str):
            raise TypeError("source must be Malloy text")

        async def format(handle: Any, _signal: Any) -> str:
            return handle.format(source)

        return await self._call(format, timeout=timeout)

    async def read_model(
        self,
        source: str | Path | ModelSource,
        *,
        url: str | None = None,
        timeout: float | None = None,
    ) -> Draft:
        """Parse a Malloy model into an immutable, editable Draft.

        A Path reads Pyodide's filesystem and retains file identity for save.
        A ModelSource retains its closed imports and captured input owners.
        Structured editing accepts model documents.
        """
        self._check_open()
        if not isinstance(source, (str, Path, ModelSource)):
            raise TypeError("source must be Malloy text, a Path, or ModelSource")
        identity, text, imports, kind = open_source(
            source, url=url, document_kind=None, root=Path.cwd()
        )
        if kind != "model":
            raise ValueError("Structured authoring requires a .malloy document")
        inputs = source.inputs if isinstance(source, ModelSource) else ()
        path = source.resolve() if isinstance(source, Path) else None

        async def read_model(handle: Any, _signal: Any) -> Draft:
            parsed = from_wire(
                msgspec.json.decode(handle.syntax(text, identity), type=SyntaxNode),
                {value.reference: value for value in inputs},
            )
            if not isinstance(parsed, Syntax):
                raise TypeError("Compiler returned a scalar for a model document")
            return Draft(
                parsed, identity, imports, path, text if path is not None else None
            )

        return await self._call(read_model, timeout=timeout)

    async def __aenter__(self) -> Self:
        async def ready(_handle: Any, _signal: Any) -> None:
            return None

        try:
            await self._call(ready)
            return self
        except BaseException:
            await self.close()
            raise

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Abort pending work, settle it, and release the owned DuckDB worker."""
        if self._closing is None:
            self._closed = True
            for model in tuple(self._models):
                model.close()
            for operation in tuple(self._operations):
                operation.abort()
            if self._lifetime is not None:
                self._lifetime.abort()

            async def finish() -> None:
                closing_handle = self._handle
                try:
                    try:
                        if closing_handle is not None:
                            await closing_handle.close()
                    finally:
                        for operation in tuple(self._operations):
                            if operation.task is not None:
                                await _settle(operation.task)
                        if (
                            self._handle is not None
                            and self._handle is not closing_handle
                        ):
                            await self._handle.close()
                finally:
                    self._models.clear()
                    self._handle = None
                    self._lifetime = None

            self._closing = asyncio.create_task(finish())
        try:
            await asyncio.shield(self._closing)
        except asyncio.CancelledError:
            await _settle(self._closing)
            raise


def connect(
    *,
    runtime: Runtime | None = None,
    name: str = DEFAULT_CONNECTION,
    timeout: float = 120,
) -> Connection:
    """Create a Pyodide connection for an asynchronous context.

    ``runtime`` chooses matching DuckDB WebAssembly assets. Its HTTP(S) URLs
    must be reachable by the browser and permitted by worker and CORS policies.
    The default uses the DuckDB package's versioned assets.

    Examples
    --------
    .. code-block:: python

        from pymalloy import browser

        async with browser.connect() as connection:
            model = await connection.model(
                "run: duckdb.sql('SELECT 42 AS n') -> { select: n }"
            )
            result = await model.query().run()
        assert result.to_pylist() == [{"n": 42}]
    """
    return Connection._create(runtime=runtime, name=name, timeout=timeout)
