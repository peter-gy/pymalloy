"""Render identifiers using the pinned Malloy lexer's reserved words."""

import re

from pymalloy._lexicon import RESERVED_WORDS

_BARE_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")


def identifier(name: str) -> str:
    if not isinstance(name, str) or not name or any(ord(c) < 32 for c in name):
        raise ValueError(
            "Malloy names require nonempty text without control characters"
        )
    if _BARE_IDENTIFIER.fullmatch(name) and name.lower() not in RESERVED_WORDS:
        return name
    return "`" + name.replace("\\", "\\\\").replace("`", "\\`") + "`"
