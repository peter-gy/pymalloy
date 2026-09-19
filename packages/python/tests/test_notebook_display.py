from decimal import Decimal

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from traitlets import TraitError

import pymalloy as pm
from pymalloy.analysis import to_dict


def send_custom(widget, content):
    widget._handle_msg(
        {
            "content": {"data": {"method": "custom", "content": content}},
            "buffers": [],
        }
    )


@pytest.fixture
def notebook_request(monkeypatch):
    def request(widget, inputs=None):
        replies = []
        monkeypatch.setattr(
            widget, "send", lambda content, buffers: replies.append((content, buffers))
        )
        send_custom(
            widget,
            {
                "kind": "pymalloy-request",
                "id": "preview",
                "input": widget.get_state()["_input"] if inputs is None else inputs,
            },
        )
        assert len(replies) == 1
        reply, buffers = replies[0]
        assert reply["kind"] == "pymalloy-response"
        assert reply["id"] == "preview"
        return reply["response"], buffers

    return request


def test_expression_and_fragment_outputs_expose_authored_structure():
    expression = pm.col("orders", "amount").sum().doc("Booked amount in USD.")
    assert expression._repr_mimebundle_(include=["text/plain"]) == {
        "text/plain": "orders.amount.sum()"
    }
    widget = expression._display_()
    try:
        definition = to_dict(widget.get_state()["_definition"])
        assert definition["notebook"]["execution"] is None
        assert definition["notebook"]["references"] == ["orders.amount"]
        assert definition["notebook"]["annotations"] == ["Booked amount in USD."]
        assert widget._input["action"] == "inspect"
    finally:
        widget.close()
    block = pm.query(
        pm.group_by(pm.col("region")),
        pm.aggregate(revenue=expression),
        pm.where(pm.call("coalesce", pm.col("kind"), pm.given("fallback")) == "chosen"),
    ).doc("Totals by region.\nAmounts are USD; refunds are excluded.")
    widget = block._display_()
    try:
        info = to_dict(widget._definition["notebook"])
        assert info["source"] == block.text
        assert '#" Booked amount in USD.' in info["source"]
        assert info["annotations"] == [
            "Totals by region.\nAmounts are USD; refunds are excluded.",
            "Booked amount in USD.",
        ]
        assert info["references"] == ["$fallback", "kind", "orders.amount", "region"]
        assert info["bindings"] == [
            {"name": "revenue", "kind": "field", "source": "orders.amount.sum()"}
        ]
        assert info["execution"] is None
    finally:
        widget.close()


def test_captured_source_inspection_and_retry_publish_valid_parquet(monkeypatch):
    source = pm.data(pa.table({"amount": [20, 22]}), name="orders")
    captured = source.inputs[0]
    materialize = type(captured).materialize

    def fail_capture(_self):
        raise OSError("Capture storage unavailable")

    monkeypatch.setattr(type(captured), "materialize", fail_capture)
    widget = source._display_()
    try:
        assert to_dict(widget._definition["notebook"])["inputs"] == [
            {"name": "orders", "rows": 2}
        ]
        assert widget._definition["files"] == {}
        assert widget._input["action"] == "inspect"
        definition, inputs = widget._definition, widget._input
        request = {"revision": inputs["revision"], "action": "run"}
        widget.set_state({"_request": request})
        assert widget.state["status"] == "error"
        assert widget.state["error"] == "Capture storage unavailable"
        assert widget._definition == definition
        assert widget._input == inputs
        monkeypatch.setattr(type(captured), "materialize", materialize)
        widget.set_state({"_request": request})
        assert widget.state["status"] == "idle"
        assert widget._input["action"] == "run"
        assert widget._input["revision"] == inputs["revision"] + 1
        data = widget._definition["files"][captured.reference]
        assert pq.read_table(pa.BufferReader(data)).to_pylist() == [
            {"amount": 20},
            {"amount": 22},
        ]
    finally:
        widget.close()


def test_native_query_display_uses_the_borrowed_connection_and_preserves_exact_values(
    notebook_request,
):
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE values_table AS SELECT 9007199254740993::BIGINT AS id, 1.2300::DECIMAL(12,4) AS amount, [1, NULL, 3] AS nested FROM range(30)"
        )
        model = pm.model(
            "run: duckdb.table('values_table') -> {select: *}", connection=connection
        )
        try:
            widget = model.query()._display_()
            try:
                assert widget._definition["notebook"]["execution"] == "python"
                assert widget.state["status"] == "idle"
                assert notebook_request(widget)[0]["kind"] == "error"
                widget.set_state(
                    {
                        "_request": {
                            "revision": widget._input["revision"],
                            "action": "run",
                        }
                    }
                )
                response, buffers = notebook_request(widget)
                assert response["kind"] == "result"
                result = pa.ipc.open_stream(buffers[0]).read_all()
                assert result.num_rows == 20
                assert result.to_pylist()[0] == {
                    "id": 9007199254740993,
                    "amount": Decimal("1.2300"),
                    "nested": [1, None, 3],
                }
                widget.query = "missing"
                widget.set_state(
                    {
                        "_request": {
                            "revision": widget._input["revision"],
                            "action": "run",
                        }
                    }
                )
                assert "Unknown query" in notebook_request(widget)[0]["message"]
                stale = dict(widget._input)
                widget.givens = {}
                widget.source = model.query()
                assert notebook_request(widget, stale)[0]["kind"] == "error"
            finally:
                widget.close()
            assert not model.closed
            with pytest.raises(TraitError, match="existing Python context"):
                pm.MalloyWidget(model, files={"values_table": "id\n1\n"})
        finally:
            model.close()
        assert connection.execute("SELECT count(*) FROM values_table").fetchone() == (
            30,
        )


def test_transient_views_close_after_the_last_view_and_can_be_displayed_again():
    expression = pm.col("amount")
    widget = expression._display_()
    for id in ("first", "second"):
        send_custom(widget, {"kind": "pymalloy-view", "action": "mount", "id": id})
    send_custom(widget, {"kind": "pymalloy-view", "action": "unmount", "id": "first"})
    assert widget.state["status"] == "idle"
    send_custom(widget, {"kind": "pymalloy-view", "action": "unmount", "id": "second"})
    assert widget.state["status"] == "closed"
    with pytest.raises(TraitError, match="closed"):
        widget.source = "run: missing"
    fresh = expression._display_()
    assert fresh.state["status"] == "idle"
    fresh.close()


def test_materialized_result_display_requires_no_live_model(notebook_request):
    result = pm.run(
        "run: duckdb.sql('SELECT 42 AS answer FROM range(30)') -> {select: answer}"
    )
    widget = result._display_()
    try:
        response, buffers = notebook_request(widget)
        assert response["kind"] == "result"
        widget.close()
        assert (
            pa.ipc.open_stream(buffers[0]).read_all().to_pylist()
            == [{"answer": 42}] * 20
        )
        assert result.arrow().num_rows == 30
    finally:
        widget.close()
