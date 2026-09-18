"""Emit native constructors for recognizable syntax and preserve other fragments verbatim."""

from __future__ import annotations

import json
import keyword
from collections.abc import Mapping
from typing import TYPE_CHECKING

from pymalloy._expression_ops import to_python
from pymalloy._identifiers import identifier
from pymalloy._syntax import Fragment, _annotation
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


def _description(
    notes: tuple[str | Fragment | Expr | TableReference, ...],
) -> str | None:
    if (
        len(notes) != 1
        or not isinstance(notes[0], Fragment)
        or notes[0].kind != "annotation"
    ):
        return None
    note = notes[0]
    lines = note.text.splitlines()
    if not all(line.startswith('#" ') for line in lines):
        return None
    value = "\n".join(line[3:] for line in lines)
    return value if value.strip() and _annotation(value).text == note.text else None


def _clauses(node: Fragment) -> list[Fragment] | None:
    parts = node.parts
    if not parts or parts[0] != "{\n" or parts[-1] != "}" or (len(parts) - 2) % 3:
        return None
    clauses = []
    for start in range(1, len(parts) - 1, 3):
        prefix, clause, suffix = parts[start : start + 3]
        if prefix != "  " or suffix != "\n" or not isinstance(clause, Fragment):
            return None
        clauses.append(clause)
    return clauses


class _Emitter:
    def __init__(self, inputs: Mapping[str, str]) -> None:
        self.inputs = inputs

    def _binding(self, node: Fragment, depth: int) -> str | None:
        if node.name is None or len(node.parts) < 2:
            return None
        notes, prefix, value = node.parts[:-2], node.parts[-2], node.parts[-1]
        if prefix != identifier(node.name) + " is " or not isinstance(
            value, (Fragment, Expr)
        ):
            return None
        rendered = self._fragment(value, depth)
        if notes:
            description = _description(notes)
            if description is None:
                return None
            rendered += f".doc({description!r})"
        if node.name.isidentifier() and not keyword.iskeyword(node.name):
            return f"{node.name}={rendered}"
        return "**{" + repr(node.name) + ": " + rendered + "}"

    def _arguments(self, node: Fragment, prefix: str, depth: int) -> list[str] | None:
        if not node.parts or node.parts[0] != prefix:
            return None
        args = []
        names = set()
        expected = (
            "query"
            if prefix in {"view: ", "nest: ", "query: "}
            else "source"
            if prefix == "source: "
            else "field"
        )
        for index, part in enumerate(node.parts[1:]):
            if index % 2:
                if part != ", ":
                    return None
            elif isinstance(part, Expr):
                if names:
                    return None
                args.append(self._fragment(part, depth))
            elif isinstance(part, Fragment):
                if part.kind != expected or part.name in names:
                    return None
                names.add(part.name)
                value = self._binding(part, depth)
                if value is None:
                    return None
                args.append(value)
            else:
                return None
        return args if args and len(node.parts) % 2 == 0 else None

    def _constructor(self, node: Fragment, depth: int) -> str | None:
        if node.kind != "expression":
            return None
        parts = node.parts
        if len(parts) == 1 and isinstance(parts[0], TableReference):
            return self._fragment(parts[0], depth)
        if len(parts) == 1 and isinstance(parts[0], str):
            text = parts[0]
            for name in ("table", "sql"):
                prefix = f"duckdb.{name}("
                if text.startswith(prefix) and text.endswith(")"):
                    try:
                        value = json.loads(text[len(prefix) : -1])
                    except ValueError:
                        continue
                    if (
                        isinstance(value, str)
                        and text == prefix + json.dumps(value, ensure_ascii=False) + ")"
                    ):
                        return f"pm.{name}({value!r})"
            if text.startswith("`") and text.endswith("`"):
                name = text[1:-1].replace("\\`", "`").replace("\\\\", "\\")
                if name and identifier(name) == text:
                    return f"pm.ref({name!r})"
        for name in (
            "dimension",
            "measure",
            "view",
            "nest",
            "group_by",
            "select",
            "aggregate",
        ):
            args = self._arguments(node, name + ": ", depth + 1)
            if args is not None:
                return _call("pm." + name, args, depth)
        if (
            len(parts) == 2
            and parts[0] in ("where: ", "having: ")
            and isinstance(parts[1], Expr)
        ):
            return _call(
                "pm." + str(parts[0])[:-2], [self._fragment(parts[1], depth + 1)], depth
            )
        clauses = _clauses(node)
        if clauses is not None:
            return _call(
                "pm.query", [self._fragment(c, depth + 1) for c in clauses], depth
            )
        if parts and isinstance(parts[-1], Fragment):
            description = _description(parts[:-1])
            if description is not None:
                return self._fragment(parts[-1], depth) + f".doc({description!r})"
        if (
            len(parts) == 3
            and isinstance(parts[0], Fragment)
            and parts[1] == " extend "
            and isinstance(parts[2], Fragment)
        ):
            clauses = _clauses(parts[2])
            if clauses is not None:
                return _call(
                    self._fragment(parts[0], depth) + ".extend",
                    [self._fragment(c, depth + 1) for c in clauses],
                    depth,
                )
        if len(parts) >= 3 and len(parts) % 2 and isinstance(parts[0], Fragment):
            stages = parts[2::2]
            if all(p == " -> " for p in parts[1::2]) and all(
                isinstance(p, Fragment) for p in stages
            ):
                return _call(
                    self._fragment(parts[0], depth) + ".pipe",
                    [
                        self._fragment(p, depth + 1)
                        for p in stages
                        if isinstance(p, Fragment)
                    ],
                    depth,
                )
        return None

    def _fragment(self, node: Fragment | Expr | TableReference, depth: int) -> str:
        if isinstance(node, TableReference):
            if node.data is not None:
                return self.inputs[node.data.name]
            canonical = TableReference(node.connection, node.path).text
            if node.connection == "duckdb" and node.text == canonical:
                return f"pm.table({node.path!r})"
            return f"pm.syntax({node.text!r})"
        if isinstance(node, Expr):
            return to_python(node._node)
        constructor = self._constructor(node, depth)
        if constructor is not None:
            return constructor
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
        declarations = []
        for part in draft.syntax.parts:
            if isinstance(part, str) and part in {"", "\n"}:
                continue
            if not isinstance(part, Fragment):
                break
            for kind, method in [("source", "define"), ("query", "queries")]:
                args = self._arguments(part, kind + ": ", 1)
                if args is not None:
                    declarations.append((method, args, part.text))
                    break
            else:
                break
        else:
            if draft.text == "".join(text + "\n" for _, _, text in declarations):
                result = _call("pm.draft", options, 0)
                for method, args, _ in declarations:
                    result = _call(result + "." + method, args, 0)
                return (
                    "import datetime\nimport pymalloy as pm\n\n"
                    + name
                    + " = "
                    + result
                    + "\n"
                )
        parts = [
            repr(p) if isinstance(p, str) else self._fragment(p, 1)
            for p in draft.syntax.parts
        ]
        return (
            "import datetime\nimport pymalloy as pm\n\n"
            + name
            + " = "
            + _call("pm.draft", parts + options, 0)
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
    reserved = {name, *bindings.values()}
    references = {}
    prelude = []
    for index, key in enumerate(sorted(bindings)):
        variable = f"_pymalloy_input_{index}"
        while variable in reserved:
            variable += "_"
        reserved.add(variable)
        references[key] = variable
        prelude.append(f"{variable} = pm.data({bindings[key]}, name={key!r})\n")
    source = _Emitter(references).source(draft, name)
    if not prelude:
        return source
    imports, body = source.split("\n\n", 1)
    return imports + "\n\n" + "".join(prelude) + "\n" + body
