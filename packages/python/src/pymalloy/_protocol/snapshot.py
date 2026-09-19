from collections.abc import Mapping
from types import MappingProxyType
from typing import Any


def freeze(value: Any) -> Any:
    """Detach containers once and expose a recursively immutable snapshot."""
    if value is None or isinstance(value, (str, bytes, int, float)):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value
