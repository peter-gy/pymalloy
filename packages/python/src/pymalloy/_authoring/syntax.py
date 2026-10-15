"""Immutable, lossless Malloy syntax with scoped named expression slots."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from functools import cached_property
from typing import TYPE_CHECKING, Self, get_args

from pymalloy._authoring.annotations import annotation_text
from pymalloy._authoring.identifiers import identifier
from pymalloy._authoring.operations import normalize
from pymalloy._authoring.tables import TableReference
from pymalloy._model.inputs import Input
from pymalloy._notebook import NotebookDisplay
from pymalloy._protocol.records import (
    ScalarSyntax,
    SyntaxNode,
    SyntaxOperation,
    SyntaxOperationKind,
    TableSyntax,
)
from pymalloy._protocol.records import (
    SyntaxKind as Kind,
)
from pymalloy.expressions import Expr

if TYPE_CHECKING:
    from pymalloy.authoring import Source, View

_KINDS = frozenset(get_args(Kind.__value__))


@dataclass(frozen=True, eq=False)
class Syntax(NotebookDisplay):
    """Lossless syntax shared by parser projections and typed authoring values."""

    parts: tuple[str | Syntax | Expr | TableReference, ...]
    kind: Kind = "expression"
    name: str | None = None
    _operation: SyntaxOperation | None = None
    _layout: bool = False

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"Unknown syntax kind: {self.kind}")
        if not isinstance(self.parts, tuple) or not all(
            isinstance(p, (str, Syntax, Expr, TableReference)) for p in self.parts
        ):
            raise TypeError("Syntax parts must be a tuple of strings or fragments")
        if self.kind in {"source", "query", "field"}:
            if not isinstance(self.name, str) or not self.name:
                raise ValueError("A binding requires a name")
            if sum(_is_expression(p) for p in self.parts) != 1 or any(
                child.kind not in {"expression", "annotation", "clause"}
                for child in self._children
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
    def _children(self) -> tuple[Syntax, ...]:
        return tuple(p for p in self.parts if isinstance(p, Syntax))

    @cached_property
    def text(self) -> str:
        """Return Malloy text, retaining logical captured-input references."""
        return self.render()

    def render(self, *, materialize: bool = False) -> str:
        """Render source/query syntax, optionally materializing captured inputs.

        Parameters
        ----------
        materialize : bool, default False
            Replace captured-input references with owned temporary Parquet paths.
            Each capture writes and verifies Parquet once. Keep the owning fragment
            alive while using those paths. False retains portable logical references.

        Returns
        -------
        str
            Malloy text. Runtime and export APIs normally manage materialization.

        Examples
        --------
        >>> import pymalloy as pm
        >>> pm.source("orders").render()
        'orders'
        """
        parts = []
        pending: list[tuple[str | Syntax | Expr | TableReference, int]] = [(self, 0)]
        while pending:
            part, depth = pending.pop()
            if isinstance(part, Syntax):
                if part._layout and part.kind == "annotation":
                    lines = "".join(str(value) for value in part.parts).splitlines(
                        keepends=True
                    )
                    parts.append(("  " * depth).join(lines))
                elif part._layout and (keyword := _listed_keyword(part)):
                    children = tuple(
                        child
                        for child in part.parts
                        if isinstance(child, (Syntax, Expr))
                    )
                    for index in range(len(children) - 1, -1, -1):
                        child = children[index]
                        if index < len(children) - 1:
                            pending.append(("\n", depth))
                        pending.append((child, depth + 1))
                        pending.append(("  " * (depth + 1), depth))
                    pending.append((keyword + ":\n", depth))
                elif (
                    part._layout
                    and part._operation is not None
                    and part._operation.kind == "block"
                ):
                    pending.append(("  " * depth + "}", depth))
                    for clause in reversed(part._children):
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
                            isinstance(previous, Syntax)
                            and previous.kind == "annotation"
                            and previous._layout
                            and (
                                isinstance(value, str)
                                and part._layout
                                or isinstance(value, Syntax)
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
    def inputs(self) -> tuple[Input, ...]:
        """Return distinct captured input owners ordered by logical name."""
        found: dict[str, Input] = {}
        pending: list[Syntax] = [self]
        while pending:
            node = pending.pop()
            for part in node.parts:
                if isinstance(part, Syntax):
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
            if isinstance(part, Syntax):
                pending.extend(part.parts)
            else:
                text = part if isinstance(part, str) else part.text
                if text:
                    return "" if text.endswith("\n") else "\n"
        return ""

    def _bindings(self) -> Iterator[Syntax]:
        pending = list(reversed(self._children))
        while pending:
            child = pending.pop()
            if child.kind in {"source", "query", "field"}:
                yield child
            elif child.kind != "annotation":
                pending.extend(reversed(child._children))

    @property
    def names(self) -> tuple[str, ...]:
        """Return binding names owned by this scope in authored order."""
        return tuple(node.name for node in self._bindings() if node.name is not None)

    def _binding(self, name: str) -> Syntax:
        return self._select((name,))[name]

    @cached_property
    def _scope(self) -> Mapping[str, Syntax | None]:
        # A present None marks ambiguity without retaining duplicate binding lists.
        bindings: dict[str, Syntax | None] = {}
        for node in self._bindings():
            if node.name is not None:
                bindings[node.name] = None if node.name in bindings else node
        return bindings

    def _select(self, names: Iterable[str]) -> dict[str, Syntax]:
        selected = {}
        for name in names:
            if name not in self._scope:
                raise KeyError(name)
            found = self._scope[name]
            if found is None:
                raise ValueError(f"Binding {name!r} is ambiguous in this scope")
            selected[name] = found
        return selected

    def __getitem__(self, name: str) -> Source | View | Expr:
        """Select a named right-hand side within this editing scope.

        Parameters
        ----------
        name : str
            Source, query, or field binding in this scope. Missing names raise
            KeyError and ambiguous names raise ValueError.

        Returns
        -------
        Source, View, or Expr
            The bound expression. Nested sources/views are separate editing scopes.

        Examples
        --------
        >>> import pymalloy as pm
        >>> source = pm.table("orders.parquet").measure(revenue=pm.col("amount").sum())
        >>> source["revenue"].text
        'amount.sum()'
        """
        from pymalloy.authoring import Source, View

        target = self._binding(name)
        value = next(
            child
            for child in target.parts
            if isinstance(child, (Syntax, Expr)) and _is_expression(child)
        )

        if isinstance(value, Expr):
            return value
        cls = Source if target.kind == "source" or self.kind == "document" else View
        return cls._from_syntax(value)

    def replace(self, /, **expressions: Source | View | Expr) -> Self:
        """Replace named expressions in this scope while preserving surrounding source.

        Parameters
        ----------
        **expressions : Source, View, or Expr
            Existing binding names mapped to replacements. Scalar fields require
            Expr values. Source and view bindings require their corresponding typed values. Replacements
            with annotations replace matching owned routes and preserve other routes.

        Returns
        -------
        Source or View
            A new immutable value. Named child scopes remain untouched unless explicitly
            selected and replaced. Missing names raise KeyError.

        Examples
        --------
        >>> import pymalloy as pm
        >>> source = pm.table("orders.parquet").measure(revenue=pm.col("amount").sum())
        >>> revised = source.replace(revenue=pm.col("amount").avg())
        >>> revised["revenue"].text, source["revenue"].text
        ('amount.avg()', 'amount.sum()')
        """
        replacements = {}
        for name, target in self._select(expressions).items():
            value = expressions[name]
            expected = type(self[name])
            if not isinstance(value, expected):
                raise TypeError(
                    f"Binding {name!r} requires a scalar Expr"
                    if expected is Expr
                    else f"Binding {name!r} requires {expected.__name__}"
                )
            replacements[id(target)] = (
                scalar_expression(value)
                if target.kind == "field"
                else expression(value)
            )

        def rewrite(node: Syntax) -> Syntax:
            if id(node) in replacements:
                notes, value = _notes(replacements[id(node)])
                parts = tuple(
                    value if _is_expression(p) else p
                    for p in node.parts
                    if not (
                        notes
                        and isinstance(p, Syntax)
                        and p.kind == "annotation"
                        and p.name in {note.name for note in notes}
                    )
                )
                return replace(node, parts=(*notes, *parts))
            if not node._children:
                return node
            return replace(
                node,
                parts=tuple(
                    rewrite(p)
                    if isinstance(p, Syntax)
                    and (p.name is None or id(p) in replacements)
                    else p
                    for p in node.parts
                ),
            )

        return self._from_syntax(rewrite(self))

    @classmethod
    def _from_syntax(cls, node: Syntax) -> Self:
        return cls(node.parts, node.kind, node.name, node._operation, node._layout)

    def annotate(self, text: str, *, route: str = "") -> Self:
        """Attach or replace an annotation on an unbound source/query expression.

        Parameters
        ----------
        text : str
            Nonempty annotation content, preserved as native Malloy syntax.
        route : str, default ""
            Renderer route when empty, documentation when '"', or an application
            route such as "research". Only the matching owned route is replaced.

        Returns
        -------
        Source or View
            A new annotated expression. Add annotations before binding a name.

        Examples
        --------
        >>> import pymalloy as pm
        >>> chart = pm.sql("SELECT 1 amount").view(
        ...     totals=pm.view().aggregate(n=pm.count()).annotate("bar_chart")
        ... )
        >>> candidate = pm.draft().queries(report=chart.pipe("totals").doc("Row count."))
        >>> with pm.connect() as con:
        ...     rows = con.model(candidate).query().run().to_pylist()
        >>> rows
        [{'n': 1}]
        """
        if self.kind != "expression":
            raise TypeError("Annotate an expression or clause before binding it")
        notes, value = _notes(self)
        note = _annotation(text, route)
        return self._from_syntax(
            Syntax((*(n for n in notes if n.name != route), note, value), _layout=True)
        )

    def doc(self, text: str) -> Self:
        """Attach a native Malloy description to a source or query expression.

        Parameters
        ----------
        text : str
            Nonempty description. State source grain or the question a query answers.

        Returns
        -------
        Source or View
            A new expression with its documentation route replaced.

        Examples
        --------
        >>> import pymalloy as pm
        >>> source = pm.table("orders.parquet").doc("One row per order.")
        >>> source.text.startswith('#" One row per order.')
        True
        """
        return self.annotate(text, route='"')


def _listed_keyword(clause: Syntax) -> str | None:
    """Return the keyword of a named clause that renders one binding per line."""
    if clause._operation is None:
        return None
    keyword = clause._operation.kind
    bindings = [child for child in clause._children if child.kind in {"field", "query"}]
    annotated = any(
        note.kind == "annotation" for child in bindings for note in child._children
    )
    if keyword in {"dimension", "measure", "view", "nest", "calculate"}:
        return keyword if annotated or len(bindings) > 1 else None
    return (
        keyword
        if annotated and keyword in {"group_by", "aggregate", "select"}
        else None
    )


def syntax(
    *parts: str | Syntax | Expr | TableReference,
    kind: Kind = "expression",
    name: str | None = None,
) -> Syntax:
    return Syntax(tuple(parts), kind, name)


def construct(
    operation: SyntaxOperationKind,
    *parts: str | Syntax | Expr | TableReference,
    arguments: tuple[str, ...] = (),
) -> Syntax:
    return Syntax(
        tuple(parts),
        _operation=SyntaxOperation(kind=operation, arguments=arguments),
        _layout=True,
    )


def _is_expression(value: object) -> bool:
    return isinstance(value, Expr) or (
        isinstance(value, Syntax) and value.kind == "expression"
    )


def expression(value: Syntax | Expr) -> Syntax:
    if not isinstance(value, Syntax) or value.kind != "expression":
        raise TypeError("Use a Source or View value")
    return value


def scalar_expression(value: Syntax | Expr) -> Expr:
    if not isinstance(value, Expr):
        if isinstance(value, str):
            raise TypeError(
                f"Write pm.col({value!r}) for a field or pm.lit({value!r}) for text"
            )
        raise TypeError("Use col(), lit(), or Expr.raw() for scalar expressions")
    return value


def _annotation(text: str, route: str = '"') -> Syntax:
    return Syntax(
        (annotation_text(text, route),), kind="annotation", name=route, _layout=True
    )


def _notes(value: Syntax | Expr) -> tuple[tuple[Syntax, ...], Syntax | Expr]:
    if isinstance(value, Expr):
        notes = tuple(_annotation(text, route) for route, text in value._annotations)
        return notes, Expr._from_node(
            value._node, source=value._source
        ) if notes else value
    if (
        len(value.parts) >= 2
        and isinstance(value.parts[-1], Syntax)
        and all(
            isinstance(p, Syntax) and p.kind == "annotation" for p in value.parts[:-1]
        )
    ):
        return value._children[:-1], value._children[-1]
    return (), value


def binding(kind: Kind, name: str, value: Syntax | Expr) -> Syntax:
    notes, value = _notes(
        scalar_expression(value) if kind == "field" else expression(value)
    )
    return Syntax(
        (*notes, identifier(name) + " is ", value), kind=kind, name=name, _layout=True
    )


def block(clauses: tuple[Syntax, ...]) -> Syntax:
    parts: list[str | Syntax] = ["{\n"]
    for clause in clauses:
        if not isinstance(clause, Syntax) or clause.kind not in {
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
    values: Mapping[str, Syntax | Expr],
    *,
    kind: Kind = "field",
) -> Syntax:
    if not values:
        raise ValueError(f"{keyword} requires a named expression")
    parts: list[str | Syntax] = [keyword + ": "]
    for index, (name, value) in enumerate(values.items()):
        if index:
            parts.append(", ")
        parts.append(binding(kind, name, value))
    return construct(keyword, *parts)


def from_wire(
    node: SyntaxNode, inputs: Mapping[str, Input] | None = None
) -> Syntax | Expr | TableReference:
    if isinstance(node, TableSyntax):
        data = (inputs or {}).get(node.path)
        return TableReference(node.connection, node.path, node.source, data)
    if isinstance(node, ScalarSyntax):
        return Expr._from_node(normalize(node.scalar), source=node.source)
    parts = tuple(p if isinstance(p, str) else from_wire(p, inputs) for p in node.parts)
    operation = node.operation
    return Syntax(
        parts,
        node.kind,
        node.name,
        None
        if operation is None
        else SyntaxOperation(kind=operation.kind, arguments=tuple(operation.arguments)),
    )
