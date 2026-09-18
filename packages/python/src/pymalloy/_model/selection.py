from collections.abc import Sequence


def query_names(queries: Sequence[str] | None, *, all: bool) -> tuple[str, ...] | None:
    """Distinguish default selection from an explicit ordered query list."""
    if type(all) is not bool:
        raise TypeError("all must be a boolean")
    if queries is None:
        return None
    if isinstance(queries, str | bytes) or not isinstance(queries, Sequence):
        raise TypeError("queries must be a sequence of query names")
    if all:
        raise ValueError("Pass query names or all=True")
    names = tuple(queries)
    if any(not isinstance(name, str) for name in names):
        raise TypeError("Query names must be strings")
    return names
