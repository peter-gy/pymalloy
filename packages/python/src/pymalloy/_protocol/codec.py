from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from operator import itemgetter
from typing import Any

import msgspec
from msgspec import Struct

from pymalloy._protocol.records import State


def to_dict(value: Any) -> Any:
    """Use Python field names while preserving authored dictionary keys."""
    if isinstance(value, Struct):
        result = {
            field.name: to_dict(item)
            for field in msgspec.structs.fields(value)
            if (item := getattr(value, field.name)) is not msgspec.UNSET
        }
        config = value.__struct_config__
        if config.tag is not None:
            result[config.tag_field] = config.tag
        return result
    if isinstance(value, Mapping):
        return {key: to_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_dict(item) for item in value]
    return value


def decode_state(wire: dict[str, Any]) -> dict[str, Any]:
    try:
        json.dumps(wire, allow_nan=False)
    except ValueError as error:
        raise ValueError(
            "Browser result and diagnostics must contain finite JSON values"
        ) from error
    validated = msgspec.convert(wire, State, strict=True)
    state = {
        "status": validated.status,
        "queries": to_dict(validated.queries),
        "error": validated.error,
        "diagnostics": to_dict(validated.diagnostics),
        "inspection": to_dict(validated.inspection),
        "result": msgspec.to_builtins(validated.result),
    }
    result = wire["result"]
    state.update(sql=None, columns=[], rows=[])
    if result is None:
        return state
    fields = result["schema"]["fields"]
    data = result.get("data")
    if data is None or data["kind"] != "array_cell":
        raise ValueError("Widget results require an array of record cells")
    row = _record_decoder(fields)
    state.update(
        sql=result.get("sql"),
        columns=[field["name"] for field in fields],
        rows=[row(value) for value in data["array_value"]],
    )
    return state


type CellDecoder = Callable[[dict[str, Any]], Any]


def _checked(kind: str, decode: CellDecoder, *, nullable: bool = True) -> CellDecoder:
    def cell(value: dict[str, Any]) -> Any:
        if nullable and value["kind"] == "null_cell":
            return None
        if value["kind"] != kind:
            raise ValueError(f"Expected {kind}, received {value['kind']}")
        return decode(value)

    return cell


def _record_decoder(
    fields: list[dict[str, Any]], *, nullable: bool = False
) -> CellDecoder:
    columns = [(field["name"], _cell_decoder(field["type"])) for field in fields]

    def record(value: dict[str, Any]) -> dict[str, Any]:
        return {
            name: decode(item)
            for (name, decode), item in zip(columns, value["record_value"], strict=True)
        }

    return _checked("record_cell", record, nullable=nullable)


def _number(value: dict[str, Any]) -> Any:
    text = value.get("string_value")
    if text is None:
        return value["number_value"]
    if value.get("subtype") == "bigint":
        return int(text)
    if text in {"NaN", "Infinity", "-Infinity"}:
        return float(text)
    try:
        number = Decimal(text)
    except InvalidOperation as error:
        raise ValueError("Invalid exact numeric value") from error
    if not number.is_finite():
        raise ValueError("Invalid exact numeric value")
    return number


def _cell_decoder(schema: dict[str, Any]) -> CellDecoder:
    kind = schema["kind"]
    if kind == "record_type":
        return _record_decoder(schema["fields"], nullable=True)
    if kind == "array_type":
        element = _cell_decoder(schema["element_type"])
        return _checked(
            "array_cell", lambda value: [element(item) for item in value["array_value"]]
        )
    if kind == "number_type":
        return _checked("number_cell", _number)
    if kind in {"json_type", "sql_native_type"}:
        name = "json" if kind == "json_type" else "sql_native"
        return _checked(
            f"{name}_cell", lambda value: json.loads(value[f"{name}_value"])
        )
    name = {
        "string_type": "string",
        "boolean_type": "boolean",
        "date_type": "date",
        "timestamp_type": "timestamp",
        "timestamptz_type": "timestamp",
    }[kind]
    return _checked(f"{name}_cell", itemgetter(f"{name}_value"))
