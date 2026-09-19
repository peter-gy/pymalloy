"""Immutable native Malloy annotation routes."""

from __future__ import annotations


def annotation_text(text: str, route: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Annotation content must be nonempty text")
    if not isinstance(route, str) or any(c.isspace() for c in route):
        raise ValueError("Annotation routes cannot contain whitespace")
    if route in {"", '"', "!", "@", ":"}:
        prefix = route
    else:
        for opening, closing in (("(", ")"), ("[", "]"), ("{", "}"), ("<", ">")):
            if closing not in route:
                prefix = opening + route + closing
                break
        else:
            raise ValueError("Annotation route contains every closing delimiter")
    return "".join(f"#{prefix} {line}\n" for line in text.splitlines())


def annotation_content(text: str) -> str | None:
    """Read reconstructible line annotations; leave opaque native syntax intact."""
    content_lines = []
    for line in text.splitlines():
        if not line.startswith("#") or line.startswith(("#|", "##")):
            return None
        boundary = next((i for i, char in enumerate(line) if char in " \t"), None)
        if boundary is None:
            return None
        content_lines.append(line[boundary + 1 :])
    content = "\n".join(content_lines)
    return content if content.strip() else None


def with_annotation(
    notes: tuple[tuple[str, str], ...], text: str, route: str
) -> tuple[tuple[str, str], ...]:
    annotation_text(text, route)
    return tuple(note for note in notes if note[0] != route) + ((route, text),)
