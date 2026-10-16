from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable, Mapping

import msgspec

from pymalloy._model.source import (
    DocumentKind,
    local_path,
    read_text,
    resolve_document_kind,
)
from pymalloy._protocol.records import (
    Column,
    CompileError,
    CompileNeeds,
    CompilerFailure,
    HostAnswers,
    HostError,
    ParseReady,
    ParseReport,
    ParseRequest,
    Request,
    Response,
    SchemaAnswer,
    SchemaNeed,
    SchemaValue,
    URLAnswer,
    URLValue,
)
from pymalloy.errors import CompilationError, CompilerError, SchemaError

_DECODER = msgspec.json.Decoder(Response)


class Compiler:
    """Fulfil source and schema needs from the packaged compiler host."""

    def __init__(self, *, memory_mb: int = 256) -> None:
        if type(memory_mb) is not int or memory_mb <= 0:
            raise ValueError("compiler_memory_mb must be a positive integer")
        if sys.platform == "emscripten":
            raise ImportError(
                "pymalloy.parse(), format(), and read_model() require native Python. "
                "In Pyodide, use the async parse(), format(), and read_model() "
                "methods on a browser.connect() connection."
            )
        try:
            from pymalloy._native import Compiler as NativeCompiler
        except ModuleNotFoundError as error:
            if error.name != "pymalloy._native":
                raise
            raise ImportError(
                "Compiler tooling requires a native PyMalloy wheel. "
                "In Pyodide, use browser.connect() for asynchronous execution."
            ) from error
        self._native = NativeCompiler(memory_mb=memory_mb)
        self._pid = os.getpid()
        self._active_thread: int | None = None
        self.sources: dict[str, str] = {}

    @property
    def closed(self) -> bool:
        return self._pid != os.getpid() or self._native.closed

    def _check_process(self) -> None:
        if self._pid != os.getpid():
            raise CompilerError(
                "Compiler owners cannot be reused after fork. "
                "Start a fresh process with spawn."
            )

    def parse(
        self,
        source: str,
        *,
        url: str,
        document_kind: DocumentKind | None = None,
        deadline: float,
    ) -> ParseReport:
        return self.request(
            ParseRequest(
                source=source,
                url=url,
                document_kind=resolve_document_kind(url, document_kind),
            ),
            ParseReady,
            describe=lambda sql: [],
            deadline=deadline,
        ).report

    def request[T](
        self,
        request: Request,
        response_type: type[T],
        *,
        describe: Callable[[SchemaNeed], list[Column]],
        deadline: float,
        imports: Mapping[str, str] | None = None,
    ) -> T:
        def check_deadline() -> float:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Compiler deadline exceeded")
            return remaining

        def read(url: str) -> str:
            if imports is not None:
                if url not in imports:
                    raise ValueError(f"Source bundle is missing '{url}'")
                text = imports[url]
            else:
                text = read_text(local_path(url))
            self.sources[url] = text
            return text

        self._check_process()
        if self._active_thread == threading.get_ident():
            raise CompilerError("Compiler operations cannot reenter their active owner")
        schema_error = None
        answers: bytes | None = None
        self._active_thread = threading.get_ident()
        try:
            job = self._native.start(msgspec.json.encode(request))
            try:
                while True:
                    response = _DECODER.decode(
                        job.step(answers, timeout=check_deadline())
                    )
                    if isinstance(response, CompilerFailure):
                        raise CompilerError(response.message)
                    if isinstance(response, CompileError):
                        raise CompilationError(
                            response.message, diagnostics=response.diagnostics
                        ) from schema_error
                    if not isinstance(response, CompileNeeds):
                        if not isinstance(response, response_type):
                            raise CompilerError(
                                f"Unexpected compiler response: {type(response).__name__}"
                            )
                        return response
                    urls: dict[str, URLAnswer] = {}
                    schemas: dict[str, SchemaAnswer] = {}
                    for url in response.needs.urls:
                        check_deadline()
                        try:
                            urls[url] = URLValue(value=read(url))
                        except (OSError, ValueError) as error:
                            urls[url] = HostError(error=str(error))
                    for need in response.needs.schemas:
                        check_deadline()
                        try:
                            schemas[need.key] = SchemaValue(value=tuple(describe(need)))
                        except SchemaError as error:
                            schema_error = error
                            schemas[need.key] = HostError(error=str(error))
                    answers = msgspec.json.encode(
                        HostAnswers(urls=urls, schemas=schemas)
                    )
            finally:
                job.close()
        except CompilationError:
            raise
        except (RuntimeError, MemoryError, msgspec.DecodeError) as error:
            self.close()
            raise CompilerError(str(error)) from error
        except BaseException:
            self.close()
            raise
        finally:
            self._active_thread = None

    def close(self) -> None:
        if self._pid == os.getpid():
            self._native.close()
