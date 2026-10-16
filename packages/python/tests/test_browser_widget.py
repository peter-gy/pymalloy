import asyncio
import sys
from types import SimpleNamespace

import msgspec

from pymalloy import MalloyWidget
from pymalloy._browser.model import Result
from pymalloy._notebook import NotebookDisplay
from pymalloy._notebook.subject import Subject, info
from pymalloy._protocol.records import NotebookError


def result_payload():
    return {
        "sql": "SELECT 9007199254740993 AS amount",
        "columns": [{"name": "amount", "type": "BIGINT"}],
        "malloy": {
            "connection_name": "duckdb",
            "sql": "SELECT 9007199254740993 AS amount",
            "schema": {
                "fields": [
                    {
                        "kind": "dimension",
                        "name": "amount",
                        "type": {"kind": "number_type", "subtype": "bigint"},
                    }
                ]
            },
            "data": {
                "kind": "array_cell",
                "array_value": [
                    {
                        "kind": "record_cell",
                        "record_value": [
                            {
                                "kind": "number_cell",
                                "number_value": 0,
                                "string_value": "9007199254740993",
                                "subtype": "bigint",
                            }
                        ],
                    }
                ],
            },
        },
    }


def send_preview(widget, identifier):
    widget._handle_msg(
        {
            "content": {
                "data": {
                    "method": "custom",
                    "content": {
                        "kind": "pymalloy-request",
                        "id": identifier,
                        "input": widget._input,
                    },
                }
            },
            "buffers": [],
        }
    )


def test_browser_result_widget_returns_detached_exact_cells(monkeypatch):
    result = Result._create(msgspec.json.encode(result_payload()).decode())
    monkeypatch.setitem(sys.modules, "pyarrow", None)
    widget = MalloyWidget(result)
    try:
        replies = []
        widget.send = lambda content, buffers=None: replies.append((content, buffers))
        send_preview(widget, "preview")
        response, buffers = replies[0]
        assert response["id"] == "preview"
        assert response["response"]["kind"] == "malloy"
        assert (
            response["response"]["result"]["data"]["array_value"][0]["record_value"][0][
                "string_value"
            ]
            == "9007199254740993"
        )
        assert buffers == []
        response["response"]["result"]["data"]["array_value"] = []
        assert result.to_pylist() == [{"amount": 9007199254740993}]
    finally:
        widget.close()


def test_browser_comm_accepts_nullable_query_selection(monkeypatch):
    widget = MalloyWidget(
        Result._create(msgspec.json.encode(result_payload()).decode())
    )
    try:
        null = object()
        inputs = {**widget._input, "query": null}
        replies = []
        widget.send = lambda content, buffers=None: replies.append(content)
        monkeypatch.setitem(sys.modules, "pyodide.ffi", SimpleNamespace(jsnull=null))
        monkeypatch.setattr(sys, "platform", "emscripten")
        widget._handle_msg(
            {
                "content": {
                    "data": {
                        "method": "custom",
                        "content": {
                            "kind": "pymalloy-request",
                            "id": "nullable-selection",
                            "input": inputs,
                        },
                    }
                },
                "buffers": [],
            }
        )
        assert replies[0]["response"]["kind"] == "malloy"
        assert (
            replies[0]["response"]["result"]["data"]["array_value"][0]["record_value"][
                0
            ]["string_value"]
            == "9007199254740993"
        )
    finally:
        widget.close()


class PausedDisplay(NotebookDisplay):
    def __init__(self, respond):
        self.subject = Subject(info("Model", "run: example", "python"), respond=respond)

    def _notebook_subject(self):
        return self.subject


def test_widget_input_revision_cancels_its_pending_python_preview():
    async def scenario():
        started = asyncio.Event()
        cancelled = asyncio.Event()
        blocker = asyncio.Event()
        calls = 0

        async def respond(_request):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                try:
                    await blocker.wait()
                finally:
                    cancelled.set()
            return NotebookError(
                message="Current preview completed", diagnostics=()
            ), []

        replies = asyncio.Queue()
        widget = MalloyWidget(PausedDisplay(respond))
        widget.send = lambda content, buffers=None: replies.put_nowait(content)
        try:
            send_preview(widget, "first")
            await asyncio.wait_for(started.wait(), timeout=1)
            widget.givens = {"value": 2}
            send_preview(widget, "second")
            await asyncio.wait_for(cancelled.wait(), timeout=1)
            first = await asyncio.wait_for(replies.get(), timeout=1)
            second = await asyncio.wait_for(replies.get(), timeout=1)
            outcomes = {reply["id"]: reply["response"] for reply in (first, second)}
            assert outcomes["first"]["message"] == "The displayed request was cancelled"
            assert outcomes["second"]["message"] == "Current preview completed"
            assert widget.state["status"] == "idle"
        finally:
            widget.close()

    asyncio.run(scenario())


def test_widget_close_cancels_its_pending_python_preview():
    async def scenario():
        started = asyncio.Event()
        cancelled = asyncio.Event()
        blocker = asyncio.Event()

        async def respond(_request):
            started.set()
            try:
                await blocker.wait()
            finally:
                cancelled.set()
            return NotebookError(message="Preview completed", diagnostics=()), []

        widget = MalloyWidget(PausedDisplay(respond))
        replies = []
        widget.send = lambda content, buffers=None: replies.append(content)
        send_preview(widget, "preview")
        await asyncio.wait_for(started.wait(), timeout=1)
        widget.close()
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        assert widget.state["status"] == "closed"
        assert replies == []

    asyncio.run(scenario())
