from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def _given(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean", "value": value}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Given numbers must be finite")
        return {"type": "number", "value": value}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Given numbers must be finite")
        value = str(value)
    if isinstance(value, (date, datetime)):
        value = value.isoformat()
    if isinstance(value, str):
        return {"type": "string", "value": value}
    if isinstance(value, (list, tuple)):
        return {"type": "array", "value": [_given(item) for item in value]}
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return {
            "type": "record",
            "value": {key: _given(item) for key, item in value.items()},
        }
    raise TypeError(f"Unsupported given value: {type(value).__name__}")


def encode_givens(values: Mapping[str, Any] | None) -> dict[str, Any]:
    if values is None:
        return {}
    if not isinstance(values, Mapping) or not all(
        isinstance(key, str) for key in values
    ):
        raise TypeError("givens must be a mapping with string keys")
    return {key: _given(value) for key, value in values.items()}


def given_values(encoded: Mapping[str, Any]) -> dict[str, Any]:
    """Return serializable Python values with the same compiler bindings."""

    def value(item: dict[str, Any]) -> Any:
        match item["type"]:
            case "null":
                return None
            case "integer":
                return int(item["value"])
            case "array":
                return [value(child) for child in item["value"]]
            case "record":
                return {key: value(child) for key, child in item["value"].items()}
            case _:
                return item["value"]

    return {key: value(item) for key, item in encoded.items()}
