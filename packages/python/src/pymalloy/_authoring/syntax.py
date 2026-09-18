"""Immutable, lossless Malloy syntax with scoped named expression slots."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from functools import cached_property
from typing import Literal

from pymalloy._authoring.annotations import annotation_text
from pymalloy._authoring.identifiers import identifier
from pymalloy._authoring.operations import normalize
from pymalloy._authoring.tables import TableReference
from pymalloy._model.inputs import DataInput
from pymalloy._protocol.records import (
    ScalarSyntax,
    SyntaxNode,
    SyntaxOperation,
    SyntaxOperationKind,
    TableSyntax,
)
from pymalloy.expressions import Expr

Kind = Literal[
    "document", "source", "query", "field", "expression", "annotation", "clause"
]


@dataclass(frozen=True, eq=False)
class Fragment:
    """Composable Malloy syntax. Named children delimit editing scopes."""

    parts: tuple[str | Fragment | Expr | TableReference, ...]
    kind: Kind = "expression"
    name: str | None = None
    _operation: SyntaxOperation | None = None
    _layout: bool = False

    def __post_init__(self) -> None:
        if self.kind not in {
            "document",
            "source",
            "query",
            "field",
            "expression",
            "annotation",
            "clause",
        }:
            raise ValueError(f"Unknown syntax kind: {self.kind}")
        if not isinstance(self.parts, tuple) or not all(
            isinstance(p, (str, Fragment, Expr, TableReference)) for p in self.parts
        ):
            raise TypeError("Syntax parts must be a tuple of strings or fragments")
        if self.kind in {"source", "query", "field"}:
            if not isinstance(self.name, str) or not self.name:
                raise ValueError("A binding requires a name")
            if sum(_is_expression(p) for p in self.parts) != 1 or any(
                child.kind not in {"expression", "annotation", "clause"}
                for child in self._fragments
            ):
                raise ValueError(
                    "A binding requires one expression and optional annotations"
                )
        elif self.kind == "annotation":
            if not isinstance(self.name, str) or not all(
                isinstance(p, str) for p in self.parts
            ):
                raise ValueError(
                    "An annotation requires a native route and literal text"
                )
        elif self.name is not None:
            raise ValueError("Only a binding has a name")

    @cached_property
    def _fragments(self) -> tuple[Fragment, ...]:
        return tuple(p for p in self.parts if isinstance(p, Fragment))

    @cached_property
    def text(self) -> str:
        return self.render()

    def render(self, *, materialize: bool = False) -> str:
        parts = []
        pending: list[tuple[str | Fragment | Expr | TableReference, int]] = [(self, 0)]
        while pending:
            part, depth = pending.pop()
            if isinstance(part, Fragment):
                if part._layout and part.kind == "annotation":
                    lines = "".join(str(value) for value in part.parts).splitlines(
                        keepends=True
                    )
                    parts.append(("  " * depth).join(lines))
                elif (
                    part._layout
                    and part._operation is not None
                    and part._operation.kind == "block"
                ):
                    pending.append(("  " * depth + "}", depth))
                    for clause in reversed(part._fragments):
                        pending.extend(
                            (
                                ("\n", depth),
                                (clause, depth + 1),
                                ("  " * (depth + 1) if clause._layout else "", depth),
                            )
                        )
                    pending.append(("{\n", depth))
                else:
                    for index in range(len(part.parts) - 1, -1, -1):
                        value = part.parts[index]
                        pending.append((value, depth))
                        previous = part.parts[index - 1] if index else None
                        # A trailing annotation newline cannot shift an opaque child's columns.
                        if (
                            isinstance(previous, Fragment)
                            and previous.kind == "annotation"
                            and previous._layout
                            and (
                                isinstance(value, str)
                                and part._layout
                                or isinstance(value, Fragment)
                                and value._layout
                            )
                        ):
                            pending.append(("  " * depth, depth))
            elif isinstance(part, TableReference):
                parts.append(part.render(materialize=materialize))
            else:
                parts.append(part if isinstance(part, str) else part.text)
        return "".join(parts)

    @cached_property
    def inputs(self) -> tuple[DataInput, ...]:
        found: dict[str, DataInput] = {}
        pending: list[Fragment] = [self]
        while pending:
            node = pending.pop()
            for part in node.parts:
                if isinstance(part, Fragment):
                    pending.append(part)
                elif isinstance(part, TableReference) and part.data is not None:
                    previous = found.get(part.data.name)
                    if previous is not None and previous is not part.data:
                        raise ValueError(
                            f"Distinct captured inputs share the name {part.data.name!r}"
                        )
                    found[part.data.name] = part.data
        return tuple(sorted(found.values(), key=lambda value: value.name))

    @property
    def _line_break(self) -> str:
        pending = list(self.parts)
        while pending:
            part = pending.pop()
            if isinstance(part, Fragment):
                pending.extend(part.parts)
            else:
                text = part if isinstance(part, str) else part.text
                if text:
                    return "" if text.endswith("\n") else "\n"
        return ""

    def _bindings(self) -> Iterator[Fragment]:
        pending = list(reversed(self._fragments))
        while pending:
            child = pending.pop()
            if child.kind in {"source", "query", "field"}:
                yield child
            elif child.kind != "annotation":
                pending.extend(reversed(child._fragments))

    @property
    def names(self) -> tuple[str, ...]:
        """Names owned by this scope, excluding bindings inside named children."""
        return tuple(node.name for node in self._bindings() if node.name is not None)

    def _binding(self, name: str) -> Fragment:
        return self._select((name,))[name]

    @cached_property
    def _scope(self) -> Mapping[str, Fragment | None]:
        # A present None marks ambiguity without retaining duplicate binding lists.
        bindings: dict[str, Fragment | None] = {}
        for node in self._bindings():
            if node.name is not None:
                bindings[node.name] = None if node.name in bindings else node
        return bindings

    def _select(self, names: Iterable[str]) -> dict[str, Fragment]:
        selected = {}
        for name in names:
            if name not in self._scope:
                raise KeyError(name)
            found = self._scope[name]
            if found is None:
                raise ValueError(f"Binding {name!r} is ambiguous in this scope")
            selected[name] = found
        return selected

    def __getitem__(self, name: str) -> Fragment | Expr:
        return next(
            child
            for child in self._binding(name).parts
            if isinstance(child, (Fragment, Expr)) and _is_expression(child)
        )

    def replace(self, **expressions: Fragment | Expr) -> Fragment:
        """Replace named right-hand sides in this scope, preserving surrounding text."""
        replacements = {}
        for name, target in self._select(expressions).items():
            value = expressions[name]
            replacements[id(target)] = (
                scalar_expression(value)
                if target.kind == "field"
                else expression(value)
            )

        def rewrite(node: Fragment) -> Fragment:
            if id(node) in replacements:
                notes, value = _notes(replacements[id(node)])
                parts = tuple(
                    value if _is_expression(p) else p
                    for p in node.parts
                    if not (
                        notes
                        and isinstance(p, Fragment)
                        and p.kind == "annotation"
                        and p.name in {note.name for note in notes}
                    )
                )
                return replace(node, parts=(*notes, *parts))
            if not node._fragments:
                return node
            return replace(
                node,
                parts=tuple(
                    rewrite(p)
                    if isinstance(p, Fragment)
                    and (p.name is None or id(p) in replacements)
                    else p
                    for p in node.parts
                ),
            )

        return rewrite(self)

    def extend(self, *clauses: Fragment) -> Fragment:
        if not clauses:
            return self
        return self._suffix((" extend ", block(clauses)))

    def _suffix(
        self, parts: tuple[str | Fragment | Expr | TableReference, ...]
    ) -> Fragment:
        if self.kind != "expression":
            raise TypeError("Compose an expression, not a declaration")
        notes, value = _notes(self)
        result = construct(
            "extend" if parts[0] == " extend " else "pipe", value, *parts
        )
        return Fragment((*notes, result), _layout=True) if notes else result

    def pipe(self, *queries: Fragment) -> Fragment:
        if not queries:
            return self
        parts: list[str | Fragment] = []
        for query in queries:
            if not isinstance(query, Fragment):
                raise TypeError("Pipeline stages must be query fragments")
            parts.extend((" -> ", query))
        return self._suffix(tuple(parts))

    def annotate(self, text: str, *, route: str = "") -> Fragment:
        """Attach a native annotation, replacing only the same route."""
        if self.kind != "expression":
            raise TypeError("Annotate an expression or clause before binding it")
        notes, value = _notes(self)
        note = _annotation(text, route)
        return Fragment(
            (*(n for n in notes if n.name != route), note, value), _layout=True
        )

    def doc(self, text: str) -> Fragment:
        """Attach a Malloy documentation annotation at this grammar position."""
        return self.annotate(text, route='"')


def syntax(
    *parts: str | Fragment | Expr | TableReference,
    kind: Kind = "expression",
    name: str | None = None,
) -> Fragment:
    """Compose literal syntax and nested editable bindings without parsing or I/O."""
    return Fragment(tuple(parts), kind, name)


def construct(
    operation: SyntaxOperationKind,
    *parts: str | Fragment | Expr | TableReference,
    arguments: tuple[str, ...] = (),
) -> Fragment:
    return Fragment(
        tuple(parts),
        _operation=SyntaxOperation(kind=operation, arguments=arguments),
        _layout=True,
    )


def _is_expression(value: object) -> bool:
    return isinstance(value, Expr) or (
        isinstance(value, Fragment) and value.kind == "expression"
    )


def expression(value: Fragment | Expr) -> Fragment:
    if not isinstance(value, Fragment) or value.kind != "expression":
        raise TypeError("Use a source or query syntax fragment")
    return value


def scalar_expression(value: Fragment | Expr) -> Expr:
    if not isinstance(value, Expr):
        raise TypeError("Use col(), lit(), or raw_expr() for scalar expressions")
    return value


def _annotation(text: str, route: str = '"') -> Fragment:
    return Fragment(
        (annotation_text(text, route),), kind="annotation", name=route, _layout=True
    )


def _notes(value: Fragment | Expr) -> tuple[tuple[Fragment, ...], Fragment | Expr]:
    if isinstance(value, Expr):
        notes = tuple(_annotation(text, route) for route, text in value._annotations)
        return notes, Expr._from_node(
            value._node, source=value._source
        ) if notes else value
    if (
        len(value.parts) >= 2
        and isinstance(value.parts[-1], Fragment)
        and all(
            isinstance(p, Fragment) and p.kind == "annotation" for p in value.parts[:-1]
        )
    ):
        return value._fragments[:-1], value._fragments[-1]
    return (), value


def binding(kind: Kind, name: str, value: Fragment | Expr) -> Fragment:
    notes, value = _notes(
        scalar_expression(value) if kind == "field" else expression(value)
    )
    return Fragment(
        (*notes, identifier(name) + " is ", value), kind=kind, name=name, _layout=True
    )


def block(clauses: tuple[Fragment, ...]) -> Fragment:
    parts: list[str | Fragment] = ["{\n"]
    for clause in clauses:
        if not isinstance(clause, Fragment) or clause.kind not in {
            "expression",
            "annotation",
            "clause",
        }:
            raise TypeError("A clause must be an anonymous syntax fragment")
        parts.extend(("  ", clause, "\n"))
    parts.append("}")
    return construct("block", *parts)


def named_clause(
    keyword: SyntaxOperationKind,
    values: Mapping[str, Fragment | Expr],
    *,
    kind: Kind = "field",
) -> Fragment:
    if not values:
        raise ValueError(f"{keyword} requires a named expression")
    parts: list[str | Fragment] = [keyword + ": "]
    for index, (name, value) in enumerate(values.items()):
        if index:
            parts.append(", ")
        parts.append(binding(kind, name, value))
    return construct(keyword, *parts)


def from_wire(
    node: SyntaxNode, inputs: Mapping[str, DataInput] | None = None
) -> Fragment | Expr | TableReference:
    if isinstance(node, TableSyntax):
        data = (inputs or {}).get(node.path)
        return TableReference(node.connection, node.path, node.source, data)
    if isinstance(node, ScalarSyntax):
        return Expr._from_node(normalize(node.scalar), source=node.source)
    parts = tuple(p if isinstance(p, str) else from_wire(p, inputs) for p in node.parts)
    operation = node.operation
    return Fragment(
        parts,
        node.kind,
        node.name,
        None
        if operation is None
        else SyntaxOperation(kind=operation.kind, arguments=tuple(operation.arguments)),
    )
