import msgspec
import pytest

from pymalloy._protocol.givens import encode_givens, given_values
from pymalloy._protocol.records import BeginRequest, Connection, Input, Request


def test_widget_input_preserves_recursive_givens_and_required_nullable_fields():
    values = {"nested": [None, True, {"large": 2**100, "negative": -(2**100)}]}
    inputs = Input(
        revision=3,
        definition_revision=2,
        action="run",
        query=None,
        givens=encode_givens(values),
    )
    wire = msgspec.to_builtins(inputs)
    assert wire["definitionRevision"] == 2
    decoded = msgspec.json.decode(msgspec.json.encode(wire), type=Input)
    assert given_values(decoded.givens) == values
    assert decoded.query is None

    without_query = {key: value for key, value in wire.items() if key != "query"}
    with pytest.raises(msgspec.ValidationError, match="query"):
        msgspec.convert(without_query, Input)
    with pytest.raises(msgspec.ValidationError, match="unexpected"):
        msgspec.convert({**wire, "unexpected": True}, Input)


def test_compiler_request_preserves_wire_aliases_and_optional_field_omission():
    request = BeginRequest(
        url="file:///model.malloy",
        document_kind="model",
        connection=Connection(name="warehouse", dialect="duckdb"),
    )
    encoded = msgspec.json.encode(request)
    wire = msgspec.json.decode(encoded)
    assert wire["op"] == "begin"
    assert wire["documentKind"] == "model"
    assert "source" not in wire
    assert msgspec.json.decode(encoded, type=Request) == request

    with pytest.raises(msgspec.ValidationError, match="source"):
        msgspec.convert({**wire, "source": None}, Request)
