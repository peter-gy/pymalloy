from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from pymalloy._errors import CompilationError, CompilerError, SchemaError
from pymalloy._records import (
    CompileError,
    CompileNeeds,
    CompilerFailure,
    ParseReady,
    ParseReport,
    SchemaNeed,
)
from pymalloy._source import DocumentKind, read_text, resolve_document_kind

from .process import Process


class Compiler:
    """Fulfil source and schema needs from the packaged compiler server."""

    def __init__(self, *, memory_mb: int = 256, timeout: float = 30) -> None:
        self._process = Process(memory_mb=memory_mb, timeout=timeout)
        self.sources: dict[str, str] = {}

    @property
    def closed(self) -> bool:
        return self._process.closed

    def parse(
        self,
        source: str,
        *,
        url: str,
        document_kind: DocumentKind | None = None,
        deadline: float,
    ) -> ParseReport:
        return self.request(
            {
                "op": "parse",
                "source": source,
                "url": url,
                "documentKind": resolve_document_kind(url, document_kind),
            },
            ParseReady,
            describe=lambda sql: [],
            deadline=deadline,
        ).report

    def request[T](
        self,
        request: dict[str, Any],
        response_type: type[T],
        *,
        describe: Callable[[SchemaNeed], list[dict[str, str]]],
        deadline: float,
        imports: Mapping[str, str] | None = None,
    ) -> T:
        def check_deadline() -> None:
            if time.monotonic() >= deadline:
                raise TimeoutError("Compiler deadline exceeded")

        def read(url: str) -> str:
            if imports is not None:
                if url not in imports:
                    raise ValueError(f"Source bundle is missing '{url}'")
                text = imports[url]
            else:
                parsed = urlsplit(url)
                if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
                    raise ValueError(f"Import '{url}' must be a local file")
                text = read_text(Path(unquote(parsed.path)))
            self.sources[url] = text
            return text

        schema_error = None
        while True:
            check_deadline()
            response = self._process.call(request, deadline)
            if isinstance(response, CompilerFailure):
                self.close()
                raise CompilerError(response.message)
            if isinstance(response, CompileError):
                raise CompilationError(
                    response.message, diagnostics=response.diagnostics
                ) from schema_error
            if not isinstance(response, CompileNeeds):
                if not isinstance(response, response_type):
                    self.close()
                    raise CompilerError(
                        f"Unexpected compiler response: {type(response).__name__}"
                    )
                return response
            fulfilled: dict[str, Any] = {"urls": {}, "schemas": {}}
            for url in response.needs.urls:
                check_deadline()
                try:
                    fulfilled["urls"][url] = {"value": read(url)}
                except (OSError, ValueError) as error:
                    fulfilled["urls"][url] = {"error": str(error)}
            for need in response.needs.schemas:
                check_deadline()
                try:
                    fulfilled["schemas"][need.key] = {"value": describe(need)}
                except SchemaError as error:
                    schema_error = error
                    fulfilled["schemas"][need.key] = {"error": str(error)}
            request = {"op": "step", "fulfilled": fulfilled}

    def close(self) -> None:
        self._process.close()
