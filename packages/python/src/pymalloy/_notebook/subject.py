"""Describe authored values without compiling them or reading their data."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import msgspec

from pymalloy._model import DEFAULT_CONNECTION
from pymalloy._model.source import DocumentKind, ModelSource
from pymalloy._protocol.givens import given_values
from pymalloy._protocol.records import (
    ExecutionKind,
    Input,
    Inspection,
    NotebookBinding,
    NotebookInfo,
    NotebookInput,
    NotebookInspection,
    NotebookResponse,
    NotebookResult,
    QueryDescriptor,
    ScalarCall,
    ScalarField,
    ScalarGiven,
)

if TYPE_CHECKING:
    from pymalloy._model.inputs import DataInput
    from pymalloy.result import Result


@dataclass
class Subject:
    info: NotebookInfo
    source: str = ""
    url: str | None = None
    document_kind: DocumentKind = "model"
    imports: Mapping[str, str] | None = None
    inputs: tuple[DataInput, ...] = ()
    queries: tuple[QueryDescriptor, ...] = ()
    inspect: Callable[[], Inspection] | None = None
    preview: Callable[[str | None, Mapping[str, Any]], Result] | None = None
    connection_name: str | None = None

    def perform(self, request: Input) -> tuple[NotebookResponse, list[memoryview]]:
        if request.action == "inspect" and self.info.execution != "result":
            raise ValueError("Choose Preview to execute this value")
        if request.action == "check":
            if self.inspect is None:
                raise ValueError("This value has no compiled model to inspect")
            return NotebookInspection(inspection=self.inspect()), []
        if self.preview is None:
            raise ValueError("This value has no Python execution context")
        selection = request.query
        if selection is not None and all(q.name != selection for q in self.queries):
            raise ValueError(f"Unknown query for this displayed value: {selection}")
        result = self.preview(request.query, given_values(request.givens))
        import pyarrow as pa

        sink = pa.BufferOutputStream()
        table = result.arrow()
        with pa.ipc.new_stream(sink, table.schema) as writer:
            writer.write_table(table)
        return NotebookResult(
            sql=result.sql,
            columns=result.columns,
            connection_name=self.connection_name or DEFAULT_CONNECTION,
        ), [memoryview(sink.getvalue())]


def info(
    kind: str,
    source: str,
    execution: ExecutionKind | None,
    message: str | None = None,
) -> NotebookInfo:
    return NotebookInfo(
        kind=kind,
        source=source,
        execution=execution,
        message=message,
        bindings=(),
        references=(),
        annotations=(),
        inputs=(),
    )


def native(
    source: ModelSource, *, kind: str, queries, inspect, preview, connection_name: str
) -> Subject:
    return Subject(
        info(
            kind,
            source.text,
            "python",
            "Preview uses the existing Python model and connection. It returns at most 20 rows.",
        ),
        source=source.text,
        url=source.url,
        document_kind=source.document_kind,
        imports=source.imports,
        queries=tuple(queries),
        inspect=inspect,
        preview=preview,
        connection_name=connection_name,
    )


def describe(value) -> Subject:
    from pymalloy._authoring.draft import Draft, draft
    from pymalloy._authoring.identifiers import identifier
    from pymalloy._authoring.syntax import Fragment
    from pymalloy._authoring.tables import TableReference
    from pymalloy.authoring import limit, query, syntax
    from pymalloy.expressions import Expr, Sort
    from pymalloy.result import Result

    if isinstance(value, str):
        return Subject(info("Model", value, "browser"), source=value)
    if isinstance(value, ModelSource):
        return Subject(
            info("Model", value.text, "browser"),
            source=value.text,
            url=value.url,
            document_kind=value.document_kind,
            imports=value.imports,
        )
    if isinstance(value, Result):
        result = Subject(
            info(
                "Result",
                value.sql,
                "result",
                f"Materialized result · {value.arrow().num_rows:,} rows. Display shows up to 20 rows without executing SQL again.",
            )
        )
        result.preview = lambda _query, _givens: Result(
            value.sql, value.columns, value.arrow().slice(0, 20)
        )
        return result

    source = value.syntax if isinstance(value, Draft) else value
    references: set[str] = set()
    paths: set[tuple[str, ...]] = set()
    annotations: list[str] = []
    pending = [source]
    independent_source = False
    while pending:
        node = pending.pop()
        if isinstance(node, Sort):
            pending.append(node.expression)
        elif isinstance(node, Expr):
            annotations.extend(
                f"{route or 'render'}: {text}" for route, text in node._annotations
            )
            scalars = [node._node]
            while scalars:
                scalar = scalars.pop()
                if isinstance(scalar, ScalarField):
                    paths.add(tuple(scalar.path))
                elif isinstance(scalar, ScalarGiven):
                    references.add("$" + scalar.name)
                elif isinstance(scalar, ScalarCall):
                    if scalar.receiver:
                        paths.add(tuple(scalar.receiver))
                    scalars.extend(scalar.args)
                elif isinstance(scalar, msgspec.Struct):
                    scalars.extend(msgspec.structs.astuple(scalar))
                elif isinstance(scalar, (list, tuple)):
                    scalars.extend(scalar)
        elif isinstance(node, TableReference):
            independent_source = True
        elif isinstance(node, Fragment):
            if node.kind == "annotation":
                annotations.append(node.text.strip())
            elif node._operation and node._operation.kind == "sql":
                independent_source = True
            elif node._operation and node._operation.kind == "ref":
                paths.add((node._operation.arguments[0],))
            pending.extend(reversed(node.parts))

    references.update(".".join(identifier(part) for part in path) for path in paths)
    bindings = ()
    inputs = ()
    if isinstance(source, Fragment):
        bindings = tuple(
            NotebookBinding(name=name, kind=binding.kind, source=source[name].text)
            for name, binding in source._scope.items()
            if binding is not None
        )
        inputs = source.inputs

    text, url, imports, message = "", None, None, None
    if isinstance(value, Draft):
        kind = "Model"
        text, url, imports = value.text, value.url, value.imports
    elif isinstance(value, Fragment):
        operation = value._operation.kind if value._operation else None
        kind = {
            "sql": "SQL source",
            "block": "Query block",
            "pipe": "Query",
            "extend": "Source",
        }.get(
            operation or "",
            operation.replace("_", " ").title()
            if operation
            else "Captured source"
            if inputs
            else value.kind.title(),
        )
        if value.kind == "document":
            text = value.text
        elif independent_source and value.kind == "expression":
            text = (
                draft()
                .define(preview_source=value)
                .append(
                    "run: preview_source -> ",
                    query(syntax("select: *", kind="clause"), limit(20)),
                )
            ).text
            message = "A source preview selects up to 20 rows. Compose a model to choose a different query."
        else:
            message = "Compose this fragment into a source or model to resolve its references and run it."
    elif isinstance(value, Expr):
        kind = "Expression"
        message = "Use this expression in select, dimension, measure, or aggregate. Its type and source scope are resolved by Malloy when the model compiles."
    elif isinstance(value, Sort):
        kind = "Sort direction"
        message = "Use this value in order_by to order a query result."
    else:
        raise TypeError(
            "Display requires Malloy text, an expression, fragment, draft, source snapshot, model, query, or result"
        )
    return Subject(
        NotebookInfo(
            kind=kind,
            source=value.text,
            execution="browser" if text or isinstance(value, Draft) else None,
            message=message,
            bindings=bindings,
            references=tuple(sorted(references)),
            annotations=tuple(dict.fromkeys(annotations)),
            inputs=tuple(
                NotebookInput(name=item.name, rows=item.rows) for item in inputs
            ),
        ),
        source=text,
        url=url,
        imports=imports,
        inputs=inputs,
    )
