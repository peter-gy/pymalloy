"""Emit Python constructors from parser-owned structure, preserving opaque syntax."""

from __future__ import annotations

import keyword
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

from pymalloy._authoring.annotations import annotation_content
from pymalloy._authoring.identifiers import identifier
from pymalloy._authoring.operations import KINDS, to_python
from pymalloy._authoring.syntax import Syntax
from pymalloy._authoring.tables import TableReference
from pymalloy._model import DEFAULT_CONNECTION
from pymalloy.expressions import Expr

if TYPE_CHECKING:
    from pymalloy._authoring.draft import Draft


def _call(name: str, args: list[str], depth: int) -> str:
    if not args:
        return name + "()"
    pad = "    " * depth
    return (
        name + "(\n" + "".join(pad + "    " + arg + ",\n" for arg in args) + pad + ")"
    )


def _annotation_suffix(notes: list[Syntax]) -> str | None:
    routes: set[str] = set()
    suffix = ""
    for note in notes:
        if note.name is None or note.name in routes:
            return None
        routes.add(note.name)
        content = annotation_content(note.text)
        if content is None:
            return None
        suffix += (
            f".doc({content!r})"
            if note.name == '"'
            else f".annotate({content!r}, route={note.name!r})"
        )
    return suffix


class _Emitter:
    def __init__(self, inputs: Mapping[str, str]) -> None:
        self.inputs = inputs

    def _binding(
        self, node: Syntax, depth: int, category: str = "Source"
    ) -> str | None:
        values = [
            part
            for part in node.parts
            if isinstance(part, Expr)
            or isinstance(part, Syntax)
            and part.kind == "expression"
        ]
        notes = [
            part
            for part in node.parts
            if isinstance(part, Syntax) and part.kind == "annotation"
        ]
        if (
            node.name is None
            or len(values) != 1
            or re.fullmatch(
                r"\s*" + re.escape(identifier(node.name)) + r"\s+is\s*",
                "".join(part for part in node.parts if isinstance(part, str)),
            )
            is None
            or any(
                isinstance(part, str)
                and any(marker in part for marker in ("#", "//", "/*"))
                for part in node.parts
            )
        ):
            return None
        suffix = _annotation_suffix(notes)
        if suffix is None:
            return None
        rendered = (
            self._fragment(
                values[0],
                depth,
                "View" if node.kind == "query" and category != "Draft" else "Source",
            )
            + suffix
        )
        if node.name.isidentifier() and not keyword.iskeyword(node.name):
            return f"{node.name}={rendered}"
        return "**{" + repr(node.name) + ": " + rendered + "}"

    def _arguments(
        self, node: Syntax, depth: int, category: str = "Source"
    ) -> list[str] | None:
        args = []
        names: set[str] = set()
        for part in node.parts:
            if isinstance(part, str):
                # Parser-identified clauses can still own comments or unsupported
                # operands between editable children. Keep those clauses lossless.
                if "#" in part or "//" in part or "/*" in part:
                    return None
                continue
            if isinstance(part, Expr):
                if names:
                    return None
                args.append(self._fragment(part, depth))
            elif isinstance(part, Syntax) and part.kind in {
                "source",
                "query",
                "field",
            }:
                if part.name is None or part.name in names:
                    return None
                names.add(part.name)
                value = self._binding(part, depth, category)
                if value is None:
                    return None
                args.append(value)
            else:
                return None
        return args or None

    def _clause(self, node: Syntax, depth: int) -> str | None:
        operation = node._operation
        if operation is None:
            return self._join(node, depth)
        kind, values = operation.kind, operation.arguments
        method = KINDS[kind][0]
        children = [part for part in node.parts if not isinstance(part, str)]
        if any(
            isinstance(part, str)
            and any(marker in part for marker in ("#", "//", "/*"))
            for part in node.parts
        ):
            return None
        if kind in {"limit", "primary_key"}:
            value = str(int(values[0])) if kind == "limit" else repr(values[0])
            return f".{method}({value})"
        if kind == "order_by":
            args = [self._fragment(child, depth + 1) for child in children]
        elif kind in {"where", "having"}:
            args = (
                [self._fragment(child, depth + 1) for child in children]
                if len(children) == 1 and isinstance(children[0], Expr)
                else None
            )
        else:
            args = self._arguments(node, depth + 1)
        return None if not args else _call("." + method, args, depth)

    def _join(self, node: Syntax, depth: int) -> str | None:
        if not node.parts or not isinstance(node.parts[0], str):
            return None
        keyword = node.parts[0].strip().removesuffix(":")
        if (
            keyword not in {"join_one", "join_many", "join_cross"}
            or len(node._fragments) != 1
        ):
            return None
        bound = node._fragments[0]
        if bound.kind != "source" or bound.name is None:
            return None
        values = [
            part
            for part in bound.parts
            if isinstance(part, Syntax) and part.kind == "expression"
        ]
        conditions = [
            part
            for part in bound.parts
            if isinstance(part, Syntax) and part.kind == "clause"
        ]
        if len(values) != 1 or any(
            isinstance(part, str)
            and any(marker in part for marker in ("#", "//", "/*"))
            for part in bound.parts
        ):
            return None
        suffix = _annotation_suffix(
            [part for part in bound._fragments if part.kind == "annotation"]
        )
        if suffix is None:
            return None
        args = [repr(bound.name), self._fragment(values[0], depth + 1) + suffix]
        if conditions:
            condition = conditions[0]
            if (
                len(conditions) != 1
                or len(condition.parts) != 1
                or not isinstance(condition.parts[0], Expr)
            ):
                return None
            args.append("on=" + self._fragment(condition.parts[0], depth + 1))
        elif keyword != "join_cross":
            return None
        return _call("." + keyword, args, depth)

    def _chain(self, node: Syntax, base: str, depth: int) -> str | None:
        suffixes = []
        for index, part in enumerate(node.parts):
            if isinstance(part, str):
                remainder = part
                if index == 0:
                    remainder = remainder.removeprefix("{")
                if index == len(node.parts) - 1:
                    remainder = remainder.removesuffix("}")
                if remainder.strip().strip(";").strip():
                    return None
            elif isinstance(part, Syntax):
                suffix = self._clause(part, depth)
                if suffix is None:
                    return None
                suffixes.append(suffix)
            else:
                return None
        return base + "".join(suffixes)

    def _constructor(self, node: Syntax, depth: int, category: str) -> str | None:
        operation = node._operation
        if operation is None:
            return None
        kind, values = operation.kind, operation.arguments
        constructor = KINDS[kind][0]
        if kind != "block" and any(
            isinstance(part, str)
            and any(marker in part for marker in ("#", "//", "/*"))
            for part in node.parts
        ):
            return None
        children = [part for part in node.parts if not isinstance(part, str)]
        if kind == "ref":
            return (
                f"pm.View.raw({node.text!r})"
                if category == "View"
                else f"pm.{constructor}({values[0]!r})"
            )
        if kind == "sql":
            connection = (
                "" if values[1] == DEFAULT_CONNECTION else f", connection={values[1]!r}"
            )
            return f"pm.{constructor}({values[0]!r}{connection})"
        if (
            kind in {"asc", "desc"}
            and len(children) == 1
            and isinstance(children[0], Expr)
        ):
            return self._fragment(children[0], depth) + f".{constructor}()"
        if kind == "block":
            return self._chain(node, "pm.view()", depth)
        if kind == "extend" and len(children) == 2 and isinstance(children[1], Syntax):
            return self._chain(children[1], self._fragment(children[0], depth), depth)
        if kind == "pipe" and len(children) >= 2:
            args = [
                repr(child._operation.arguments[0])
                if isinstance(child, Syntax)
                and child._operation
                and child._operation.kind == "ref"
                else self._fragment(child, depth + 1, "View")
                for child in children[1:]
            ]
            return _call(
                self._fragment(children[0], depth, category) + ".pipe", args, depth
            )
        return None

    def _fragment(
        self, node: Syntax | Expr | TableReference, depth: int, category: str = "Source"
    ) -> str:
        if isinstance(node, TableReference):
            if node.data is not None:
                return self.inputs[node.data.name]
            connection = (
                ""
                if node.connection == DEFAULT_CONNECTION
                else f", connection={node.connection!r}"
            )
            return f"pm.table({node.path!r}{connection})"
        if isinstance(node, Expr):
            result = to_python(node._node)
            for route, text in node._annotations:
                result += f".annotate({text!r}, route={route!r})"
            return result
        constructor = self._constructor(node, depth, category)
        if constructor is not None:
            return constructor
        if node.kind == "expression":
            if len(node.parts) == 1 and not isinstance(node.parts[0], str):
                return self._fragment(node.parts[0], depth, category)
            notes = [
                part
                for part in node.parts[:-1]
                if isinstance(part, Syntax) and part.kind == "annotation"
            ]
            if (
                notes
                and len(notes) == len(node.parts) - 1
                and isinstance(node.parts[-1], Syntax)
            ):
                suffix = _annotation_suffix(notes)
                if suffix is not None:
                    return self._fragment(node.parts[-1], depth, category) + suffix
        return _call(
            f"pm.{category}.raw",
            [
                repr(part)
                if isinstance(part, str)
                else self._fragment(part, depth + 1, category)
                for part in node.parts
            ],
            depth,
        )

    def source(self, draft: Draft, name: str) -> str:
        options = [f"url={draft.url!r}"]
        if draft.imports is not None:
            options.append(f"imports={dict(draft.imports)!r}")
        calls = [_call("pm.draft", options, 0)]
        for part in draft.syntax.parts:
            if isinstance(part, str) and not part.strip():
                continue
            if (
                isinstance(part, Syntax)
                and part._operation is not None
                and part._operation.kind in {"source", "query"}
            ):
                args = self._arguments(part, 1, "Draft")
                if args is not None:
                    method = (
                        "sources" if part._operation.kind == "source" else "queries"
                    )
                    calls.append(_call("." + method, args, 0))
                    continue
            if isinstance(part, Syntax) and (
                part.kind in {"source", "query", "field"} or part.names
            ):
                # Parsing recovers editing scopes in declarations with opaque grammar.
                return (
                    f"import pymalloy as pm\n\n{name} = pm.read_model({draft.text!r}, url={draft.url!r})\n"
                    if draft.imports is None
                    else f"import pymalloy as pm\n\n{name} = pm.read_model(pm.ModelSource({draft.url!r}, {draft.text!r}, {dict(draft.imports)!r}))\n"
                )
            value = repr(part) if isinstance(part, str) else self._fragment(part, 1)
            calls.append(_call(".append", [value], 0))
        return (
            "import datetime\nimport pymalloy as pm\n\n"
            + name
            + " = "
            + "".join(calls)
            + "\n"
        )


def python_source(
    draft: Draft, name: str, *, inputs: Mapping[str, str] | None = None
) -> str:
    bindings = dict(inputs or {})
    required = {value.name for value in draft.inputs}
    if set(bindings) != required:
        raise ValueError(
            f"Python reconstruction requires bindings for inputs {sorted(required)!r}; use bundle(accepted) for portable replay"
        )
    if any(
        not value.isidentifier() or keyword.iskeyword(value)
        for value in bindings.values()
    ):
        raise ValueError("Input bindings must name Python variables")
    connections: dict[str, set[str]] = {}
    pending = [draft.syntax]
    while pending:
        fragment = pending.pop()
        for part in fragment.parts:
            if isinstance(part, Syntax):
                pending.append(part)
            elif isinstance(part, TableReference) and part.data is not None:
                connections.setdefault(part.data.name, set()).add(part.connection)
    if any(len(values) != 1 for values in connections.values()):
        raise ValueError(
            "Python reconstruction requires one connection per captured input"
        )
    reserved = {name, *bindings.values()}
    references = {}
    prelude = []
    for index, key in enumerate(sorted(bindings)):
        variable = f"_pymalloy_input_{index}"
        while variable in reserved:
            variable += "_"
        reserved.add(variable)
        references[key] = variable
        connection = next(iter(connections[key]))
        option = (
            "" if connection == DEFAULT_CONNECTION else f", connection={connection!r}"
        )
        prelude.append(f"{variable} = pm.data({bindings[key]}, name={key!r}{option})\n")
    source = _Emitter(references).source(draft, name)
    if not prelude:
        return source
    imports, body = source.split("\n\n", 1)
    return imports + "\n\n" + "".join(prelude) + "\n" + body
