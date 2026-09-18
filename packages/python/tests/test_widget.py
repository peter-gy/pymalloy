import math
import subprocess
import sys

import pytest
from traitlets import TraitError

from pymalloy import MalloyWidget, ModelSource, browser


def browser_state(widget, rows=None, **changes):
    rows = rows if rows is not None else [{"value": 42}]

    def shape(value):
        if isinstance(value, list):
            return {"kind": "array_type", "element_type": shape(value[0])}
        if isinstance(value, dict):
            return {
                "kind": "record_type",
                "fields": [{"name": k, "type": shape(v)} for k, v in value.items()],
            }
        return {"kind": "number_type"}

    def cell(value):
        if isinstance(value, list):
            return {"kind": "array_cell", "array_value": [cell(v) for v in value]}
        if isinstance(value, dict):
            return {
                "kind": "record_cell",
                "record_value": [cell(v) for v in value.values()],
            }
        if type(value) is int and abs(value) > 2**53:
            return {
                "kind": "number_cell",
                "subtype": "bigint",
                "number_value": float(value),
                "string_value": str(value),
            }
        if isinstance(value, float) and not math.isfinite(value):
            return {
                "kind": "number_cell",
                "number_value": 0,
                "string_value": "Infinity",
            }
        return {"kind": "number_cell", "number_value": value}

    return {
        "revision": widget._input["revision"],
        "status": "ready",
        "queries": [{"name": "run:0", "kind": "run", "location": None}],
        "result": {
            "sql": "SELECT 42 AS value",
            "connection_name": "duckdb",
            "schema": {
                "fields": [
                    {"kind": "dimension", **f}
                    for f in shape(rows[0] if rows else {"value": 0})["fields"]
                ]
            },
            "data": cell(rows),
        },
        "error": None,
        "diagnostics": [],
        **changes,
    }


def test_widget_publishes_source_query_files_and_exact_givens():
    files = {"orders.csv": "region,amount\nNorth,42\n", "part.parquet": b"PAR1"}
    givens = {
        "amount": 9223372036854775807,
        "options": [True, {"lower": -9007199254740993}],
    }
    widget = MalloyWidget("source: orders", files=files, givens=givens)
    try:
        state = widget.get_state()
        assert state["_definition"]["source"] == "source: orders"
        assert state["_definition"]["connectionName"] == "duckdb"
        assert state["_definition"]["files"] == {
            "orders.csv": b"region,amount\nNorth,42\n",
            "part.parquet": b"PAR1",
        }
        from pymalloy._protocol.givens import given_values

        assert given_values(state["_input"]["givens"]) == givens
        assert widget.givens == {
            "amount": 9223372036854775807,
            "options": (True, {"lower": -9007199254740993}),
        }
        assert widget.files["part.parquet"] is files["part.parquet"]
        files["part.parquet"] = b"changed"
        givens["options"].append("changed")
        assert widget.files["part.parquet"] == b"PAR1"
        assert widget.givens["options"] == (True, {"lower": -9007199254740993})
        revision = state["_input"]["revision"]
        widget.set_state({"query": "orders.by_region"})
        assert widget.query == "orders.by_region"
        assert widget.get_state()["_input"]["query"] == "orders.by_region"
        assert widget.get_state()["_input"]["revision"] > revision
        assert widget.get_state()["_definition"] == state["_definition"]
        assert (
            widget.get_state()["_input"]["definitionRevision"]
            == state["_definition"]["revision"]
        )
    finally:
        widget.close()


def test_widget_captured_source_preserves_identity_imports_and_revision():
    imports = {
        "file:///project/parts/orders.malloy": "source: orders is duckdb.table('data.csv')"
    }
    source = ModelSource(
        url="file:///project/report.malloynb",
        text=">>>malloy\nimport './parts/orders.malloy'\nrun: orders\n",
        imports=imports,
    )
    widget = MalloyWidget(source)
    try:
        imports.clear()
        definition = widget.get_state()["_definition"]
        assert definition["source"] == source.text
        assert definition["url"] == source.url
        assert definition["documentKind"] == "notebook"
        assert definition["imports"] == dict(source.imports)
        old = browser_state(widget)
        widget.source = ModelSource(source.url, source.text, {})
        assert widget.get_state()["_definition"]["imports"] == {}
        assert widget.get_state()["_definition"]["revision"] > definition["revision"]
        widget.set_state({"_state": old})
        assert widget.state["status"] == "idle"
        widget.source = ModelSource(source.url, "run: orders", document_kind="model")
        assert widget.get_state()["_definition"]["documentKind"] == "model"
        widget.source = "run: orders"
        assert widget.get_state()["_definition"]["documentKind"] == "model"
        assert widget.get_state()["_definition"]["source"] == "run: orders"
        assert widget.get_state()["_definition"]["url"] is None
        assert widget.get_state()["_definition"]["imports"] is None
    finally:
        widget.close()


def test_widget_readback_preserves_nested_numbers_in_immutable_snapshots():
    widget = MalloyWidget("run: example")
    observed = []
    widget.observe(lambda change: observed.append(change.new), names="state")
    try:
        wire = browser_state(
            widget,
            rows=[
                {
                    "value": 9223372036854775807,
                    "nested": [{"small": -9007199254740993}],
                    "ratio": math.inf,
                }
            ],
        )
        widget.set_state({"_state": wire})
        retained = widget.state
        assert retained["rows"] == (
            {
                "value": 9223372036854775807,
                "nested": ({"small": -9007199254740993},),
                "ratio": math.inf,
            },
        )
        from pymalloy.analysis import to_dict

        assert to_dict(retained)["rows"][0]["nested"] == [{"small": -9007199254740993}]
        assert observed[-1] is retained
        assert widget.state is retained
        with pytest.raises(TypeError):
            retained["rows"][0]["nested"][0]["small"] = 0
        wire["result"]["data"]["array_value"].clear()
        widget.source = "run: changed"
        assert widget.state["status"] == "idle"
        assert retained["status"] == "ready"
        assert retained["rows"][0]["value"] == 9223372036854775807
        with pytest.raises(TraitError, match="read-only"):
            widget.state = {}
    finally:
        widget.close()


def test_widget_input_snapshots_require_validated_assignment():
    files = {"data.csv": {"url": "https://example.com/data.csv"}, "part": b"PAR1"}
    givens = {"options": {"minimum": 9007199254740993}, "choices": [1, 2]}
    widget = MalloyWidget("run: example", files=files, givens=givens)
    observed = {}

    def inspect(change):
        with pytest.raises(TypeError):
            change.new["unexpected"] = 1
        observed[change.name] = change.new

    widget.observe(inspect, names=["files", "givens"])
    try:
        retained_files, retained_givens = widget.files, widget.givens
        with pytest.raises(TypeError):
            retained_files["data.csv"]["url"] = "file:///private/data.csv"
        with pytest.raises(TypeError):
            retained_givens["options"]["minimum"] = float("nan")
        with pytest.raises(TraitError):
            widget.files = {
                **widget.files,
                "data.csv": {"url": "file:///private/data.csv"},
            }
        with pytest.raises(TraitError):
            widget.givens = {"options": {"minimum": float("nan")}}
        widget.files = widget.files
        widget.givens = widget.givens
        with widget.hold_trait_notifications():
            widget.files = {**widget.files, "part": b"changed"}
            widget.givens = {**widget.givens, "choices": (3, 4)}
        assert observed == {"files": widget.files, "givens": widget.givens}
        assert retained_files == files
        assert retained_givens["choices"] == (1, 2)
        assert widget.files["part"] == b"changed"
        assert widget.givens["choices"] == (3, 4)
        assert widget.get_state()["_definition"]["files"]["part"] == b"changed"
        from pymalloy._protocol.givens import given_values

        assert given_values(widget.get_state()["_input"]["givens"])["choices"] == [3, 4]
    finally:
        widget.close()


def test_widget_runtime_uses_immutable_explicit_asset_urls():
    from dataclasses import FrozenInstanceError

    bundle = browser.Bundle(
        module="https://assets.example/duckdb-mvp.wasm",
        worker="https://assets.example/duckdb-browser-mvp.worker.js",
    )
    runtime = browser.Runtime(mvp=bundle)
    widget = MalloyWidget("run: example", runtime=runtime)
    try:
        assert widget.runtime is runtime
        assert widget.get_state()["_runtime"] == {
            "mvp": {"mainModule": bundle.module, "mainWorker": bundle.worker}
        }
        with pytest.raises(FrozenInstanceError):
            bundle.module = "https://assets.example/other.wasm"
        with pytest.raises(TraitError, match="read-only"):
            widget.runtime = None
        with pytest.raises(ValueError, match="absolute HTTP"):
            browser.Bundle(module="file:///duckdb.wasm", worker=bundle.worker)
        with pytest.raises(TypeError, match="browser.Bundle"):
            browser.Runtime(mvp={})
    finally:
        widget.close()


def test_widget_revision_lifecycle_preserves_state_through_resync_and_close(
    monkeypatch,
):
    widget = MalloyWidget("run: first")
    messages = []
    monkeypatch.setattr(
        widget, "_send", lambda message, buffers=None: messages.append(message)
    )
    try:
        earlier = browser_state(widget, rows=[{"value": 1}])
        widget.source = "run: second"
        widget.set_state({"_state": earlier})
        assert widget.state["status"] == "idle"

        latest = browser_state(widget, rows=[{"value": 2}])
        widget.set_state({"_state": latest})
        assert widget.state["rows"] == ({"value": 2},)
        widget.set_state({"_state": earlier})
        assert widget.state["rows"] == ({"value": 2},)

        messages.clear()
        widget._handle_msg({"content": {"data": {"method": "request_state"}}})
        assert len(messages) == 1
        assert messages[0]["method"] == "update"
        synchronized = messages[0]["state"]
        assert synchronized["_state"] == latest
        assert synchronized["_state"]["revision"] == synchronized["_input"]["revision"]

        widget.close()
        widget.close()
        widget.set_state({"_state": browser_state(widget)})
        assert widget.state["status"] == "closed"
        with pytest.raises(TraitError, match="closed"):
            widget.source = "run: third"
    finally:
        widget.close()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": ""},
        {"connection_name": ""},
        {"connection_name": None},
        {"connection_name": 42},
        {"files": {"x": {"url": "file:///private/data.csv"}}},
        {"files": {"x": {"url": 42}}},
        {"files": {"x": 42}},
        {"files": {"": b"data"}},
        {"givens": {"x": float("nan")}},
        {"givens": {"x": float("inf")}},
        {"givens": {"x": object()}},
        {"givens": {1: "value"}},
    ],
)
def test_widget_rejects_invalid_inputs(kwargs):
    with pytest.raises(TraitError):
        MalloyWidget("run: example", **kwargs)


def test_widget_validates_new_inputs_before_publishing():
    widget = MalloyWidget(
        "run: example", files={"data.csv": {"url": "https://example.com/data.csv"}}
    )
    try:
        before = widget.get_state()["_input"]
        with pytest.raises(TraitError):
            widget.files = {"data.csv": object()}
        assert widget.get_state()["_input"] == before
        assert widget.files == {"data.csv": {"url": "https://example.com/data.csv"}}
        with pytest.raises(TraitError):
            widget._state = browser_state(widget, result={"schema": {}})
        assert widget.state["status"] == "idle"
        widget._state = browser_state(
            widget, status="error", rows=[], error="Unknown query"
        )
        assert widget.state["error"] == "Unknown query"
    finally:
        widget.close()


def test_base_installation_supports_widgets_documents_and_cli_help():
    program = """
import importlib.abc
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
class ServerImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'duckdb', 'deno', 'polars', 'pyarrow', 'marimo'}:
            raise AssertionError(f'Server dependency imported: {fullname}')
sys.meta_path.insert(0, ServerImports())
import pymalloy as pm
assert {'MalloyWidget', 'model', 'run', 'check', 'format'} <= set(dir(pm))
from pymalloy import MalloyWidget
with_widget = MalloyWidget("run: example")
assert with_widget.state["status"] == "idle"
with_widget.close()
from pymalloy.export import Document, QueryCell, jupyter
query = QueryCell('answer', 'SELECT 42 AS answer', 'select')
document = Document('Answer', (query,), Path.cwd())
notebook = __import__('json').loads(jupyter.render(document, output_path='answer.ipynb'))
assert notebook['nbformat'] == 4
assert any('SELECT 42 AS answer' in ''.join(cell['source']) for cell in notebook['cells'])
from pymalloy.cli import main
for arguments in [['--help'], ['export', '--help'], ['check', '--help'], ['format', '--help']]:
    sys.argv = ['pymalloy', *arguments]
    output = io.StringIO()
    with redirect_stdout(output):
        try:
            main()
        except SystemExit as error:
            assert error.code == 0, arguments
        else:
            raise AssertionError(arguments)
    assert 'usage:' in output.getvalue(), arguments
"""
    subprocess.run([sys.executable, "-c", program], check=True, timeout=20)


def test_cli_reports_the_extra_required_for_export(tmp_path):
    program = """
import importlib.abc
import sys
class ServerImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'duckdb':
            raise ModuleNotFoundError('duckdb')
sys.meta_path.insert(0, ServerImports())
from pymalloy.cli import main
sys.argv = ['pymalloy', 'export', 'model.malloy', '--format', 'marimo', '-o', sys.argv[1]]
main()
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path / "report.py")],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "pip install 'pymalloy[server]'" in result.stderr


def test_widget_state_observers_receive_immutable_readback():
    widget = MalloyWidget("run: example")

    def inspect(change):
        if change.new["status"] == "ready":
            with pytest.raises(TypeError):
                change.new["rows"][0]["value"] = 999

    widget.observe(inspect, names="state")
    try:
        widget.set_state({"_state": browser_state(widget)})
        assert widget.state["rows"] == ({"value": 42},)
    finally:
        widget.close()


def test_widget_diagnostics_preserve_source_locations_and_clear_on_recovery():
    widget = MalloyWidget("run: missing_source")
    diagnostic = {
        "code": "source-or-query-not-found",
        "severity": "error",
        "message": "Reference to undefined object 'missing_source'",
        "location": {
            "url": "https://pymalloy.local/model.malloy",
            "range": {
                "start": {"line": 0, "character": 5},
                "end": {"line": 0, "character": 19},
            },
        },
        "replacement": None,
        "data": {"name": "missing_source"},
        "errorTag": None,
    }
    try:
        widget.set_state(
            {
                "_state": browser_state(
                    widget,
                    status="error",
                    rows=[],
                    error=diagnostic["message"],
                    diagnostics=[diagnostic],
                )
            }
        )
        assert widget.state["diagnostics"] == (
            {
                **{k: v for k, v in diagnostic.items() if k != "errorTag"},
                "error_tag": None,
            },
        )
        snapshot = widget.state
        with pytest.raises(TypeError):
            snapshot["diagnostics"][0]["location"]["range"]["start"]["line"] = 99
        assert widget.state["diagnostics"][0]["location"]["range"]["start"]["line"] == 0
        widget.source = "run: recovered"
        assert widget.state["diagnostics"] == ()
        widget.set_state({"_state": browser_state(widget)})
        assert widget.state["status"] == "ready"
        assert widget.state["diagnostics"] == ()
    finally:
        widget.close()


@pytest.mark.parametrize(
    "diagnostic",
    [
        {
            "code": "bad",
            "severity": "error",
            "message": "Bad source",
            "location": {
                "url": "model.malloy",
                "range": {
                    "start": {"line": -1, "character": 0},
                    "end": {"line": 0, "character": 1},
                },
            },
            "replacement": None,
            "data": None,
            "errorTag": None,
        },
        {
            "code": "bad",
            "severity": "error",
            "message": "Bad source",
            "location": None,
            "replacement": None,
            "data": {"value": float("nan")},
            "errorTag": None,
        },
    ],
)
def test_widget_rejects_malformed_browser_diagnostics(diagnostic):
    widget = MalloyWidget("run: example")
    try:
        with pytest.raises(TraitError, match="diagnostic"):
            widget.set_state(
                {"_state": browser_state(widget, diagnostics=[diagnostic])}
            )
        assert widget.state["diagnostics"] == ()
    finally:
        widget.close()


def test_widget_decodes_nullable_schema_types_without_losing_exact_values():
    from decimal import Decimal

    types_and_cells = {
        "name": (
            {"kind": "string_type"},
            {"kind": "string_cell", "string_value": "Ada"},
        ),
        "active": (
            {"kind": "boolean_type"},
            {"kind": "boolean_cell", "boolean_value": True},
        ),
        "day": (
            {"kind": "date_type"},
            {"kind": "date_cell", "date_value": "2026-09-18"},
        ),
        "instant": (
            {"kind": "timestamptz_type"},
            {"kind": "timestamp_cell", "timestamp_value": "2026-09-18T00:00:00Z"},
        ),
        "amount": (
            {"kind": "number_type", "subtype": "decimal"},
            {
                "kind": "number_cell",
                "number_value": 1.23,
                "string_value": "1.2300",
                "subtype": "decimal",
            },
        ),
        "metadata": (
            {"kind": "json_type"},
            {"kind": "json_cell", "json_value": '{"tags":["exact"]}'},
        ),
        "bytes": (
            {"kind": "sql_native_type"},
            {"kind": "sql_native_cell", "sql_native_value": "[0,255]"},
        ),
    }
    widget = MalloyWidget("run: example")
    try:
        wire = browser_state(widget)
        fields = [
            {"name": name, "type": schema}
            for name, (schema, _) in types_and_cells.items()
        ]
        wire["result"]["schema"]["fields"] = [
            {
                "kind": "dimension",
                "name": "nested",
                "type": {
                    "kind": "array_type",
                    "element_type": {"kind": "record_type", "fields": fields},
                },
            },
        ]
        wire["result"]["data"] = {
            "kind": "array_cell",
            "array_value": [
                {
                    "kind": "record_cell",
                    "record_value": [
                        {
                            "kind": "array_cell",
                            "array_value": [
                                {
                                    "kind": "record_cell",
                                    "record_value": [
                                        cell for _, cell in types_and_cells.values()
                                    ],
                                },
                                {
                                    "kind": "record_cell",
                                    "record_value": [
                                        {"kind": "null_cell"} for _ in fields
                                    ],
                                },
                                {"kind": "null_cell"},
                            ],
                        }
                    ],
                }
            ],
        }
        widget.set_state({"_state": wire})
        assert widget.state["rows"] == (
            {
                "nested": (
                    {
                        "name": "Ada",
                        "active": True,
                        "day": "2026-09-18",
                        "instant": "2026-09-18T00:00:00Z",
                        "amount": Decimal("1.2300"),
                        "metadata": {"tags": ("exact",)},
                        "bytes": (0, 255),
                    },
                    dict.fromkeys(types_and_cells),
                    None,
                )
            },
        )
    finally:
        widget.close()


@pytest.mark.parametrize(
    "invalid",
    [
        "scalar",
        "nested",
        "row_width",
        "top_record",
        "null_row",
        "missing_data",
        "numeric_text",
    ],
)
def test_widget_rejects_cells_that_disagree_with_the_result_schema(invalid):
    widget = MalloyWidget("run: example")
    try:
        widget.set_state({"_state": browser_state(widget)})
        accepted = widget.state
        wire = browser_state(widget, rows=[{"value": 99}])
        result = wire["result"]
        match invalid:
            case "scalar":
                result["schema"]["fields"][0]["type"] = {"kind": "string_type"}
            case "nested":
                result["schema"]["fields"][0]["type"] = {
                    "kind": "array_type",
                    "element_type": {"kind": "string_type"},
                }
                result["data"]["array_value"][0]["record_value"][0] = {
                    "kind": "array_cell",
                    "array_value": [{"kind": "number_cell", "number_value": 99}],
                }
            case "row_width":
                result["data"]["array_value"][0]["record_value"] = []
            case "top_record":
                result["data"] = result["data"]["array_value"][0]
            case "null_row":
                result["data"]["array_value"] = [{"kind": "null_cell"}]
            case "missing_data":
                del result["data"]
            case "numeric_text":
                result["data"]["array_value"][0]["record_value"][0]["string_value"] = (
                    "not a number"
                )
        with pytest.raises(TraitError, match="Invalid browser state"):
            widget.set_state({"_state": wire})
        assert widget.state == accepted
    finally:
        widget.close()


def test_widget_connection_name_is_explicit_and_fixed_for_its_lifetime():
    widget = MalloyWidget(
        "run: analytics.sql('SELECT 42 AS answer') -> { select: answer }",
        connection_name="analytics",
    )
    try:
        assert widget.connection_name == "analytics"
        assert widget.get_state()["_definition"]["connectionName"] == "analytics"
        with pytest.raises(TraitError, match="read-only"):
            widget.connection_name = "other"
        widget.source = "run: analytics.sql('SELECT 1 AS answer') -> { select: answer }"
        assert widget.get_state()["_definition"]["connectionName"] == "analytics"
    finally:
        widget.close()
