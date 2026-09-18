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


def with_annotation(
    notes: tuple[tuple[str, str], ...], text: str, route: str
) -> tuple[tuple[str, str], ...]:
    annotation_text(text, route)
    return tuple(note for note in notes if note[0] != route) + ((route, text),)
