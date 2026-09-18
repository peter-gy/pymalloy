"""Serialize editable syntax as Python constructor calls, never executable Malloy text."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pymalloy._expression_ops import to_python
from pymalloy._syntax import Fragment
from pymalloy.expressions import Expr

if TYPE_CHECKING:
    from pymalloy._draft import Draft


def _fragment(node: Fragment | Expr, depth: int) -> str:
    if isinstance(node, Expr):
        return to_python(node._node)
    pad = "    " * depth
    pieces = [
        repr(p) if isinstance(p, str) else _fragment(p, depth + 1) for p in node.parts
    ]
    if node.kind != "expression":
        pieces.append(f"kind={node.kind!r}")
    if node.name is not None:
        pieces.append(f"name={node.name!r}")
    return (
        "pm.syntax(\n"
        + "".join(pad + "    " + item + ",\n" for item in pieces)
        + pad
        + ")"
    )


def python_source(draft: Draft, name: str) -> str:
    parts = [
        repr(p) if isinstance(p, str) else _fragment(p, 1) for p in draft.syntax.parts
    ]
    parts.append(f"url={draft.url!r}")
    if draft.imports is not None:
        parts.append(f"imports={dict(draft.imports)!r}")
    return (
        "import datetime\nimport pymalloy as pm\n\n"
        + name
        + " = pm.draft(\n"
        + "".join("    " + p + ",\n" for p in parts)
        + ")\n"
    )
