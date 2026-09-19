from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .records import (
    ArrayGiven,
    BooleanGiven,
    Given,
    IntegerGiven,
    NullGiven,
    NumberGiven,
    RecordGiven,
    StringGiven,
)


def _given(value: Any) -> Given:
    if value is None:
        return NullGiven()
    if isinstance(value, bool):
        return BooleanGiven(value=value)
    if isinstance(value, int):
        return IntegerGiven(value=str(value))
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Given numbers must be finite")
        return NumberGiven(value=value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Given numbers must be finite")
        value = str(value)
    if isinstance(value, (date, datetime)):
        value = value.isoformat()
    if isinstance(value, str):
        return StringGiven(value=value)
    if isinstance(value, (list, tuple)):
        return ArrayGiven(value=tuple(_given(item) for item in value))
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return RecordGiven(value={key: _given(item) for key, item in value.items()})
    raise TypeError(f"Unsupported given value: {type(value).__name__}")


def encode_givens(values: Mapping[str, Any] | None) -> dict[str, Given]:
    if values is None:
        return {}
    if not isinstance(values, Mapping) or not all(
        isinstance(key, str) for key in values
    ):
        raise TypeError("givens must be a mapping with string keys")
    return {key: _given(value) for key, value in values.items()}


def given_values(encoded: Mapping[str, Given]) -> dict[str, Any]:
    """Return serializable Python values with the same compiler bindings."""

    def value(item: Given) -> Any:
        match item:
            case NullGiven():
                return None
            case IntegerGiven():
                return int(item.value)
            case ArrayGiven():
                return [value(child) for child in item.value]
            case RecordGiven():
                return {key: value(child) for key, child in item.value.items()}
            case _:
                return item.value

    return {key: value(item) for key, item in encoded.items()}
