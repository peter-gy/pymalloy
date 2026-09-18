"""Emit Python constructors from parser-owned structure, preserving opaque syntax."""

from __future__ import annotations

import keyword
from collections.abc import Mapping
from typing import TYPE_CHECKING

from pymalloy._connection import DEFAULT_CONNECTION
from pymalloy._expression_ops import to_python
from pymalloy._syntax import Fragment
from pymalloy._table import TableReference
from pymalloy.expressions import Expr

if TYPE_CHECKING:
    from pymalloy._draft import Draft


def _call(name: str, args: list[str], depth: int) -> str:
    if not args:
        return name + "()"
    pad = "    " * depth
    return (
        name + "(\n" + "".join(pad + "    " + arg + ",\n" for arg in args) + pad + ")"
    )


def _annotation_suffix(notes: list[Fragment]) -> str | None:
    routes: set[str] = set()
    suffix = ""
    for note in notes:
        if note.name is None or note.name in routes:
            return None
        routes.add(note.name)
        lines = note.text.splitlines()
        content_lines = []
        for line in lines:
            if not line.startswith("#") or line.startswith(("#|", "##")):
                return None
            boundary = next((i for i, char in enumerate(line) if char in " \t"), None)
            if boundary is None:
                return None
            content_lines.append(line[boundary + 1 :])
        content = "\n".join(content_lines)
        if not content.strip():
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

    def _binding(self, node: Fragment, depth: int) -> str | None:
        values = [
            part
            for part in node.parts
            if isinstance(part, Expr)
            or isinstance(part, Fragment)
            and part.kind == "expression"
        ]
        notes = [
            part
            for part in node.parts
            if isinstance(part, Fragment) and part.kind == "annotation"
        ]
        if (
            node.name is None
            or len(values) != 1
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
        rendered = self._fragment(values[0], depth) + suffix
        if node.name.isidentifier() and not keyword.iskeyword(node.name):
            return f"{node.name}={rendered}"
        return "**{" + repr(node.name) + ": " + rendered + "}"

    def _arguments(self, node: Fragment, depth: int) -> list[str] | None:
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
            elif isinstance(part, Fragment) and part.kind in {
                "source",
                "query",
                "field",
            }:
                if part.name is None or part.name in names:
                    return None
                names.add(part.name)
                value = self._binding(part, depth)
                if value is None:
                    return None
                args.append(value)
            else:
                return None
        return args or None

    def _block_arguments(self, node: Fragment, depth: int) -> list[str]:
        args = []
        for index, part in enumerate(node.parts):
            if isinstance(part, str):
                remainder = part
                if index == 0:
                    remainder = remainder.removeprefix("{")
                if index == len(node.parts) - 1:
                    remainder = remainder.removesuffix("}")
                if remainder.strip().strip(";").strip():
                    args.append(f"pm.syntax({remainder!r})")
            else:
                args.append(self._fragment(part, depth))
        return args

    def _constructor(self, node: Fragment, depth: int) -> str | None:
        operation = node._operation
        if operation is None:
            return None
        kind, values = operation.kind, operation.arguments
        if kind != "block" and any(
            isinstance(part, str)
            and any(marker in part for marker in ("#", "//", "/*"))
            for part in node.parts
        ):
            return None
        children = [part for part in node.parts if not isinstance(part, str)]
        if kind == "ref":
            return f"pm.ref({values[0]!r})"
        if kind == "sql":
            connection = (
                "" if values[1] == DEFAULT_CONNECTION else f", connection={values[1]!r}"
            )
            return f"pm.sql({values[0]!r}{connection})"
        if kind == "order_by" and children:
            return _call(
                "pm.order_by",
                [self._fragment(child, depth + 1) for child in children],
                depth,
            )
        if (
            kind in {"asc", "desc"}
            and len(children) == 1
            and isinstance(children[0], Expr)
        ):
            return self._fragment(children[0], depth) + f".{kind}()"
        if kind == "limit":
            return f"pm.limit({int(values[0])})"
        if kind == "primary_key":
            return f"pm.primary_key({values[0]!r})"
        if kind in {
            "dimension",
            "measure",
            "view",
            "nest",
            "group_by",
            "select",
            "aggregate",
        }:
            args = self._arguments(node, depth + 1)
            return None if args is None else _call("pm." + kind, args, depth)
        if kind in {"where", "having"}:
            if len(children) == 1 and isinstance(children[0], Expr):
                return _call(
                    "pm." + kind, [self._fragment(children[0], depth + 1)], depth
                )
            return None
        if kind == "block":
            return _call("pm.query", self._block_arguments(node, depth + 1), depth)
        if (
            kind == "extend"
            and len(children) == 2
            and isinstance(children[1], Fragment)
            and children[1]._operation is not None
            and children[1]._operation.kind == "block"
        ):
            return _call(
                self._fragment(children[0], depth) + ".extend",
                self._block_arguments(children[1], depth + 1),
                depth,
            )
        if kind == "pipe" and len(children) == 2:
            return _call(
                self._fragment(children[0], depth) + ".pipe",
                [self._fragment(children[1], depth + 1)],
                depth,
            )
        return None

    def _fragment(self, node: Fragment | Expr | TableReference, depth: int) -> str:
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
        constructor = self._constructor(node, depth)
        if constructor is not None:
            return constructor
        if node.kind == "expression":
            if len(node.parts) == 1 and not isinstance(node.parts[0], str):
                return self._fragment(node.parts[0], depth)
            notes = [
                part
                for part in node.parts[:-1]
                if isinstance(part, Fragment) and part.kind == "annotation"
            ]
            if (
                notes
                and len(notes) == len(node.parts) - 1
                and isinstance(node.parts[-1], Fragment)
            ):
                suffix = _annotation_suffix(notes)
                if suffix is not None:
                    return self._fragment(node.parts[-1], depth) + suffix
        pieces = [
            repr(p) if isinstance(p, str) else self._fragment(p, depth + 1)
            for p in node.parts
        ]
        if node.kind != "expression":
            pieces.append(f"kind={node.kind!r}")
        if node.name is not None:
            pieces.append(f"name={node.name!r}")
        return _call("pm.syntax", pieces, depth)

    def source(self, draft: Draft, name: str) -> str:
        options = [f"url={draft.url!r}"]
        if draft.imports is not None:
            options.append(f"imports={dict(draft.imports)!r}")
        calls = [_call("pm.draft", options, 0)]
        for part in draft.syntax.parts:
            if isinstance(part, str) and not part.strip():
                continue
            if (
                isinstance(part, Fragment)
                and part._operation is not None
                and part._operation.kind in {"source", "query"}
            ):
                args = self._arguments(part, 1)
                if args is not None:
                    method = "define" if part._operation.kind == "source" else "queries"
                    calls.append(_call("." + method, args, 0))
                    continue
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
            if isinstance(part, Fragment):
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
