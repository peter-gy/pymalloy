"""Render and serialize the shared scalar operation records."""

from __future__ import annotations

import datetime
import json
from collections.abc import Sequence
from typing import assert_never

from pymalloy._authoring.identifiers import identifier
from pymalloy._protocol.records import (
    Branch,
    Scalar,
    ScalarBinary,
    ScalarCall,
    ScalarCase,
    ScalarCast,
    ScalarField,
    ScalarFilter,
    ScalarGiven,
    ScalarLiteral,
    ScalarNullTest,
    ScalarRaw,
    ScalarTruncate,
    ScalarUnary,
)

_MALLOY_TYPES = frozenset(
    {"number", "string", "boolean", "date", "timestamp", "timestamptz"}
)


def normalize(node: Scalar) -> Scalar:
    """Snapshot protocol sequences so expression values remain deeply immutable."""
    match node:
        case ScalarField(path=path):
            return ScalarField(path=tuple(path))
        case ScalarUnary(operator=operator, value=value):
            return ScalarUnary(operator=operator, value=normalize(value))
        case ScalarBinary(operator=operator, left=left, right=right):
            return ScalarBinary(
                operator=operator, left=normalize(left), right=normalize(right)
            )
        case ScalarCall(name=name, args=args, receiver=receiver):
            return ScalarCall(
                name=name,
                args=tuple(map(normalize, args)),
                receiver=None if receiver is None else tuple(receiver),
            )
        case ScalarCast(value=value, type=type_, safe=safe):
            return ScalarCast(value=normalize(value), type=type_, safe=safe)
        case ScalarNullTest(value=value, negated=negated):
            return ScalarNullTest(value=normalize(value), negated=negated)
        case ScalarTruncate(value=value, unit=unit):
            return ScalarTruncate(value=normalize(value), unit=unit)
        case ScalarFilter(value=value, predicate=predicate):
            return ScalarFilter(value=normalize(value), predicate=normalize(predicate))
        case ScalarCase(branches=branches, otherwise=otherwise):
            return ScalarCase(
                branches=tuple(
                    Branch(when=normalize(b.when), then=normalize(b.then))
                    for b in branches
                ),
                otherwise=normalize(otherwise),
            )
        case ScalarGiven() | ScalarLiteral() | ScalarRaw():
            return node
        case _:
            assert_never(node)


def _path(path: tuple[str, ...] | list[str]) -> str:
    return ".".join(identifier(name) for name in path)


def _function(name: str) -> str:
    return name if name.isidentifier() else identifier(name)


def _separated(values: Sequence[str | Scalar]) -> list[str | Scalar]:
    parts: list[str | Scalar] = []
    for index, value in enumerate(values):
        if index:
            parts.append(", ")
        parts.append(value)
    return parts


def render(node: Scalar) -> str:
    if isinstance(node, ScalarRaw):
        return node.code
    output: list[str] = []
    pending: list[str | Scalar] = [node]
    while pending:
        part = pending.pop()
        if isinstance(part, str):
            output.append(part)
        else:
            pending.extend(reversed(_malloy_parts(part)))
    return "".join(output)


def _malloy_parts(node: Scalar) -> Sequence[str | Scalar]:
    match node:
        case ScalarBinary(operator=operator, left=left, right=right):
            return ("(", left, " " + operator + " ", right, ")")
        case ScalarField(path=path):
            return (_path(tuple(path)),)
        case ScalarLiteral(type=kind, value=value):
            match kind:
                case "number" | "boolean" | "null":
                    return (value,)
                case "string":
                    return (json.dumps(value, ensure_ascii=False),)
                case "date":
                    return ("@" + value,)
                case "timestamp":
                    timestamp = datetime.datetime.fromisoformat(value)
                    if timestamp.utcoffset() is not None:
                        utc = timestamp.astimezone(datetime.UTC).replace(tzinfo=None)
                        return ("@" + utc.isoformat() + "[UTC]",)
                    return ("@" + timestamp.isoformat(),)
                case _:
                    assert_never(kind)
        case ScalarGiven(name=name):
            return ("$" + name,)
        case ScalarRaw(code=code):
            return ("(\n", code, "\n)")
        case ScalarUnary(operator=operator, value=value):
            return ("(" + operator + " ", value, ")")
        case ScalarCall(name=name, args=args, receiver=receiver):
            prefix = "" if receiver is None else _path(tuple(receiver)) + "."
            return (prefix + _function(name) + "(", *_separated(args), ")")
        case ScalarCast(value=value, type=type_, safe=safe):
            target = (
                type_
                if type_ in _MALLOY_TYPES
                else json.dumps(type_, ensure_ascii=False)
            )
            return ("(", value, (":::" if safe else "::") + target + ")")
        case ScalarNullTest(value=value, negated=negated):
            return ("(", value, " is not null)" if negated else " is null)")
        case ScalarTruncate(value=value, unit=unit):
            return ("(", value, ")." + unit)
        case ScalarFilter(value=value, predicate=predicate):
            return ("(", value, ") { where: ", predicate, " }")
        case ScalarCase(branches=branches, otherwise=otherwise):
            parts: list[str | Scalar] = ["(case "]
            for branch in branches:
                parts.extend(("when ", branch.when, " then ", branch.then, " "))
            return (*parts, "else ", otherwise, " end)")
        case _:
            assert_never(node)


_BINARY_PYTHON = {
    "=": "==",
    "!=": "!=",
    "<>": "!=",
    "and": "&",
    "or": "|",
    "+": "+",
    "-": "-",
    "*": "*",
    "/": "/",
    "%": "%",
    "<": "<",
    "<=": "<=",
    ">": ">",
    ">=": ">=",
}


def to_python(node: Scalar) -> str:
    """Emit symbolic constructors for supported operations and explicit raw leaves."""
    match node:
        case ScalarField(path=path):
            return "pm.col(" + ", ".join(map(repr, path)) + ")"
        case ScalarGiven(name=name):
            return f"pm.given({name!r})"
        case ScalarLiteral(type="string", value=value):
            return f"pm.lit({value!r})"
        case ScalarLiteral(type="boolean", value=value):
            return f"pm.lit({value == 'true'})"
        case ScalarLiteral(type="null"):
            return "pm.lit(None)"
        case ScalarLiteral(type="date", value=value):
            return f"pm.lit(datetime.date.fromisoformat({value!r}))"
        case ScalarLiteral(type="timestamp", value=value):
            return f"pm.lit(datetime.datetime.fromisoformat({value!r}))"
        case ScalarLiteral(value=value):
            try:
                integer = int(value)
            except ValueError:
                pass
            else:
                if str(integer) == value:
                    return f"pm.lit({integer})"
            return f"pm.number({value!r})"
        case ScalarRaw(code=code):
            return f"pm.raw_expr({code!r})"
        case ScalarUnary(operator=operator, value=value):
            return f"({'~' if operator == 'not' else '-'}{to_python(value)})"
        case ScalarBinary(operator="??", left=left, right=right):
            return f"{to_python(left)}.fill_null({to_python(right)})"
        case ScalarBinary(operator=operator, left=left, right=right):
            if operator not in _BINARY_PYTHON:
                return f"pm.raw_expr({render(node)!r})"
            return f"({to_python(left)} {_BINARY_PYTHON[operator]} {to_python(right)})"
        case ScalarCall(name=name, args=args, receiver=receiver):
            if (
                not args
                and receiver is not None
                and name in {"sum", "avg", "min", "max"}
            ):
                return "pm.col(" + ", ".join(map(repr, receiver)) + f").{name}()"
            if not args and name == "count":
                return "pm.count(" + ", ".join(map(repr, receiver or ())) + ")"
            values = [repr(name), *map(to_python, args)]
            if receiver is not None:
                values.append(f"receiver={tuple(receiver)!r}")
            return "pm.call(" + ", ".join(values) + ")"
        case ScalarCast(value=value, type=type_, safe=safe):
            return f"{to_python(value)}.cast({type_!r}, safe={safe!r})"
        case ScalarNullTest(value=value, negated=negated):
            return f"{to_python(value)}.{'is_not_null' if negated else 'is_null'}()"
        case ScalarTruncate(value=value, unit=unit):
            return f"{to_python(value)}.dt.truncate({unit!r})"
        case ScalarFilter(value=value, predicate=predicate):
            return f"{to_python(value)}.filter({to_python(predicate)})"
        case ScalarCase(branches=branches, otherwise=otherwise):
            values = [f"({to_python(b.when)}, {to_python(b.then)})" for b in branches]
            values.append(f"otherwise={to_python(otherwise)}")
            return "pm.case(" + ", ".join(values) + ")"
        case _:
            assert_never(node)
