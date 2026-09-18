import math
import subprocess
import sys

import pytest
from traitlets import TraitError

from pymalloy import Malloy, ModelSource, browser


def browser_state(widget, **changes):
    return {
        "revision": widget._input["revision"],
        "status": "ready",
        "queries": ["run:1"],
        "sql": "SELECT 42 AS value",
        "columns": ["value"],
        "rows": [{"value": 42}],
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
    widget = Malloy("source: orders", files=files, givens=givens)
    try:
        state = widget.get_state()
        assert state["_definition"]["source"] == "source: orders"
        assert state["_definition"]["files"] == {
            "orders.csv": b"region,amount\nNorth,42\n",
            "part.parquet": b"PAR1",
        }
        assert state["_input"]["givens"] == {
            "amount": "9223372036854775807",
            "options": [True, {"lower": "-9007199254740993"}],
        }
        assert state["_input"]["integer_paths"] == [["amount"], ["options", 1, "lower"]]
        assert widget.givens == givens
        files["part.parquet"] = b"changed"
        givens["options"].append("changed")
        assert widget.files["part.parquet"] == b"PAR1"
        assert widget.givens["options"] == [True, {"lower": -9007199254740993}]
        revision = state["_input"]["revision"]
        widget.set_state({"query": "orders.by_region"})
        assert widget.query == "orders.by_region"
        assert widget.get_state()["_input"]["query"] == "orders.by_region"
        assert widget.get_state()["_input"]["revision"] > revision
        assert widget.get_state()["_definition"] == state["_definition"]
        assert (
            widget.get_state()["_input"]["definition_revision"]
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
    widget = Malloy(source)
    try:
        imports.clear()
        definition = widget.get_state()["_definition"]
        assert definition["source"] == source.text
        assert definition["url"] == source.url
        assert definition["imports"] == dict(source.imports)
        old = browser_state(widget)
        widget.source = ModelSource(source.url, source.text, {})
        assert widget.get_state()["_definition"]["imports"] == {}
        assert widget.get_state()["_definition"]["revision"] > definition["revision"]
        widget.set_state({"_state": old})
        assert widget.state["status"] == "idle"
        widget.source = "run: orders"
        assert widget.get_state()["_definition"]["source"] == "run: orders"
        assert widget.get_state()["_definition"]["url"] is None
        assert widget.get_state()["_definition"]["imports"] is None
    finally:
        widget.close()


def test_widget_readback_preserves_nested_numbers_and_detaches_snapshots():
    widget = Malloy("run: example")
    observed = []
    widget.observe(lambda change: observed.append(change.new), names="state")
    try:
        wire = browser_state(
            widget,
            rows=[
                {
                    "value": "9223372036854775807",
                    "nested": [{"small": "-9007199254740993"}],
                    "ratio": None,
                }
            ],
            integer_paths=[[0, "value"], [0, "nested", 0, "small"]],
            number_paths=[{"path": [0, "ratio"], "value": "inf"}],
        )
        widget.set_state({"_state": wire})
        assert widget.state["rows"] == [
            {
                "value": 9223372036854775807,
                "nested": [{"small": -9007199254740993}],
                "ratio": math.inf,
            }
        ]
        assert observed[-1]["status"] == "ready"
        snapshot = widget.state
        snapshot["rows"][0]["nested"][0]["small"] = 0
        assert widget.state["rows"][0]["nested"][0]["small"] == -9007199254740993
        with pytest.raises(TraitError, match="read-only"):
            widget.state = {}
    finally:
        widget.close()


def test_widget_input_snapshots_require_validated_assignment():
    files = {"data.csv": {"url": "https://example.com/data.csv"}, "part": b"PAR1"}
    givens = {"options": {"minimum": 9007199254740993}}
    widget = Malloy("run: example", files=files, givens=givens)
    try:
        draft_files, draft_givens = widget.files, widget.givens
        draft_files["data.csv"]["url"] = "file:///private/data.csv"
        draft_files["part"] = b"changed"
        draft_givens["options"]["minimum"] = float("nan")
        with pytest.raises(TraitError):
            widget.files = draft_files
        with pytest.raises(TraitError):
            widget.givens = draft_givens
        widget.source = "run: changed"
        assert widget.files == files
        assert widget.givens == givens
        assert widget.get_state()["_definition"]["files"] == files
        assert widget.get_state()["_input"]["givens"] == {
            "options": {"minimum": "9007199254740993"}
        }
    finally:
        widget.close()


def test_widget_runtime_uses_immutable_explicit_asset_urls():
    from dataclasses import FrozenInstanceError

    bundle = browser.Bundle(
        module="https://assets.example/duckdb-mvp.wasm",
        worker="https://assets.example/duckdb-browser-mvp.worker.js",
    )
    runtime = browser.Runtime(mvp=bundle)
    widget = Malloy("run: example", runtime=runtime)
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


def test_widget_input_observers_receive_detached_mappings():
    widget = Malloy("run: example")

    def inspect(change):
        change.new.clear()

    widget.observe(inspect, names=["files", "givens"])
    try:
        with widget.hold_trait_notifications():
            widget.files = {"data.csv": "value\n42\n"}
            widget.givens = {"minimum": 42}
        widget.source = "run: changed"
        assert widget.files == {"data.csv": b"value\n42\n"}
        assert widget.givens == {"minimum": 42}
        assert widget.get_state()["_definition"]["files"] == widget.files
        assert widget.get_state()["_input"]["givens"] == widget.givens
    finally:
        widget.close()


def test_widget_ignores_stale_browser_results_after_edit_and_close():
    widget = Malloy("run: first")
    old = browser_state(widget)
    widget.source = "run: second"
    widget.set_state({"_state": old})
    assert widget.state["status"] == "idle"
    current = browser_state(widget, rows=[{"value": 99}])
    widget.set_state({"_state": current})
    assert widget.state["rows"] == [{"value": 99}]
    widget.close()
    widget.close()
    widget.set_state({"_state": browser_state(widget)})
    assert widget.state["status"] == "closed"
    with pytest.raises(TraitError, match="closed"):
        widget.source = "run: third"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": ""},
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
        Malloy("run: example", **kwargs)


def test_widget_validates_new_inputs_before_publishing():
    widget = Malloy(
        "run: example", files={"data.csv": {"url": "https://example.com/data.csv"}}
    )
    try:
        before = widget.get_state()["_input"]
        with pytest.raises(TraitError):
            widget.files = {"data.csv": object()}
        assert widget.get_state()["_input"] == before
        assert widget.files == {"data.csv": {"url": "https://example.com/data.csv"}}
        with pytest.raises(TraitError):
            widget._state = browser_state(widget, integer_paths=[[0, "missing"]])
        assert widget.state["status"] == "idle"
        widget._state = browser_state(
            widget, status="error", rows=[], error="Unknown query"
        )
        assert widget.state["error"] == "Unknown query"
    finally:
        widget.close()


@pytest.mark.parametrize(
    "arguments",
    [["--help"], ["export", "--help"], ["check", "--help"], ["format", "--help"]],
)
def test_cli_help_is_available_in_the_base_installation(arguments):
    program = """
import importlib.abc
import sys
class NativeImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'duckdb', 'deno', 'polars', 'pyarrow', 'sqlglot'}:
            raise ModuleNotFoundError(fullname)
sys.meta_path.insert(0, NativeImports())
from pymalloy.cli import main
sys.argv = ['pymalloy', *sys.argv[1:]]
main()
"""
    result = subprocess.run(
        [sys.executable, "-c", program, *arguments],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert result.stderr == ""


def test_cli_reports_the_extra_required_for_export(tmp_path):
    program = """
import importlib.abc
import sys
class NativeImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'duckdb':
            raise ModuleNotFoundError('duckdb')
sys.meta_path.insert(0, NativeImports())
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
    assert "pip install 'pymalloy[server,marimo]'" in result.stderr


def test_widget_state_observers_receive_detached_readback():
    widget = Malloy("run: example")

    def inspect(change):
        if change.new["status"] == "ready":
            change.new["rows"][0]["value"] = 999

    widget.observe(inspect, names="state")
    try:
        widget.set_state({"_state": browser_state(widget)})
        assert widget.state["rows"] == [{"value": 42}]
    finally:
        widget.close()


def test_widget_diagnostics_preserve_source_locations_and_clear_on_recovery():
    widget = Malloy("run: missing_source")
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
        "error_tag": None,
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
        assert widget.state["diagnostics"] == [diagnostic]
        snapshot = widget.state
        snapshot["diagnostics"][0]["location"]["range"]["start"]["line"] = 99
        assert widget.state["diagnostics"][0]["location"]["range"]["start"]["line"] == 0
        widget.source = "run: recovered"
        assert widget.state["diagnostics"] == []
        widget.set_state({"_state": browser_state(widget)})
        assert widget.state["status"] == "ready"
        assert widget.state["diagnostics"] == []
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
            "error_tag": None,
        },
        {
            "code": "bad",
            "severity": "error",
            "message": "Bad source",
            "location": None,
            "replacement": None,
            "data": {"value": float("nan")},
            "error_tag": None,
        },
    ],
)
def test_widget_rejects_malformed_browser_diagnostics(diagnostic):
    widget = Malloy("run: example")
    try:
        with pytest.raises(TraitError, match="diagnostic"):
            widget.set_state(
                {"_state": browser_state(widget, diagnostics=[diagnostic])}
            )
        assert widget.state["diagnostics"] == []
    finally:
        widget.close()
