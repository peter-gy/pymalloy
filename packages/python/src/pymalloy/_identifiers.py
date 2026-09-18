"""Quote Malloy identifiers without depending on syntax or scalar operations."""


def identifier(name: str) -> str:
    if not isinstance(name, str) or not name or any(ord(c) < 32 for c in name):
        raise ValueError(
            "Malloy names require nonempty text without control characters"
        )
    return "`" + name.replace("\\", "\\\\").replace("`", "\\`") + "`"
