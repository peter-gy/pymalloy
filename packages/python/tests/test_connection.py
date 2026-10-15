import gc
import json
import subprocess
import weakref

import duckdb
import polars as pl
import pyarrow as pa
import pytest

import pymalloy as pm
from pymalloy.analysis import to_dict
from pymalloy.authoring import Input
from pymalloy.errors import ClosedError, ValidationError

ONE = "run: duckdb.sql('SELECT 42 AS value') -> {select: value}"


def test_models_share_engine_and_keep_independent_compilers():
    with pm.connect(name="warehouse") as connection:
        native = connection.duckdb
        connection.duckdb.execute("CREATE TABLE numbers AS SELECT 42 AS value")
        first = connection.model("run: warehouse.table('numbers') -> {select: value}")
        second = connection.model("run: warehouse.table('numbers') -> {select: value}")
        first.close()
        assert first.closed
        assert second.query().run().to_pylist() == [{"value": 42}]
        assert connection.name == "warehouse"
        retained = second.query()
    assert connection.closed and second.closed
    with pytest.raises(ClosedError):
        retained.run()
    with pytest.raises(ClosedError):
        connection.model(ONE)
    with pytest.raises(duckdb.ConnectionException):
        native.execute("SELECT 1")


def test_query_keeps_connection_alive_until_release():
    connection = pm.connect()
    native = connection.duckdb
    reference = weakref.ref(connection)
    query = connection.model(ONE).query()
    del connection
    gc.collect()
    assert reference() is not None
    assert query.run().to_pylist() == [{"value": 42}]
    del query
    gc.collect()
    assert reference() is None
    with pytest.raises(duckdb.ConnectionException):
        native.execute("SELECT 1")


def test_borrowed_connection_preserves_transaction_settings_and_registrations():
    with duckdb.connect() as native:
        native.execute("SET timezone = 'America/New_York'")
        native.register("captured", pa.table({"value": [42]}))
        native.execute("BEGIN")
        native.execute("CREATE TABLE retained AS SELECT * FROM captured")
        connection = pm.connect(native)
        model = connection.model("run: duckdb.table('retained') -> {select: value}")
        assert model.query().run().to_pylist() == [{"value": 42}]
        connection.close()
        assert model.closed
        assert native.execute("SELECT current_setting('timezone')").fetchone() == (
            "America/New_York",
        )
        assert native.execute("SELECT * FROM captured").fetchall() == [(42,)]
        native.execute("ROLLBACK")
        assert native.execute("SHOW TABLES").fetchall() == [("captured",)]


@pytest.mark.parametrize(
    "options",
    [
        {"data_root": "."},
        {"read_only": True},
        {"config": {}},
        {"extensions": ("json",)},
    ],
)
def test_borrowed_connection_rejects_owned_settings(options):
    with duckdb.connect() as native:
        with pytest.raises(ValueError, match="Borrowed"):
            pm.connect(native, **options)
        assert native.execute("SELECT 42").fetchone() == (42,)


@pytest.mark.parametrize("snapshot_kind", ["model", "validation"])
def test_captured_input_snapshot_rebinds_after_collection(snapshot_kind):
    captured = pm.data(pa.table({"amount": [12, 20]}), name="orders")
    candidate = (
        pm.draft()
        .sources(orders=captured)
        .queries(
            total=pm.source("orders").pipe(
                pm.view().aggregate(amount=pm.col("amount").sum())
            )
        )
    )
    assert isinstance(captured.inputs[0], Input)
    frame = captured.inputs[0].to_arrow()
    with pm.connect() as connection:
        if snapshot_kind == "model":
            model = connection.model(candidate)
            snapshot = model.source()
            model.close()
            del model
        else:
            accepted = connection.validate(candidate).require_valid()
            snapshot = accepted.source
            del accepted
    assert snapshot.text == candidate.text
    del connection, captured, candidate
    gc.collect()
    rebound = pm.read_model(snapshot).sources(orders=pm.data(frame, name="orders"))
    with pm.connect() as connection:
        assert connection.model(rebound).query("total").run().to_pylist() == [
            {"amount": 32}
        ]


def test_validation_captures_changing_bindings_once_for_all_checks():
    class ChangingBindings(dict):
        reads = 0

        def items(self):
            self.reads += 1
            return {"minimum": 0 if self.reads == 1 else 100}.items()

    candidate = pm.draft(
        "##! experimental.givens\ngiven: minimum :: number is 0\n"
    ).sources(values=pm.sql("SELECT 42 AS amount"))
    bad = pm.source("values").pipe(
        pm.view().where(pm.col("amount") < pm.given("minimum")).select(pm.col("amount"))
    )
    bindings = ChangingBindings(minimum=0)
    with pm.connect() as connection:
        report = connection.validate(
            candidate, {"first": bad, "second": bad}, givens=bindings
        )
    assert bindings.reads == 1
    assert report.givens == {"minimum": 0}
    assert [check.status for check in report.checks] == ["passed", "passed"]
    assert [check.result.to_pylist() for check in report.checks] == [[], []]


def test_validation_error_carries_structured_report():
    with pm.connect() as connection:
        report = connection.validate(pm.draft("run: missing"))
    with pytest.raises(ValidationError) as caught:
        report.require_valid()
    assert caught.value.report is report
    assert report.diagnostics[0].code == "source-or-query-not-found"


def test_result_supports_arrow_and_polars_consumers_after_close():
    with pm.connect() as connection:
        result = (
            connection.model(
                "run: duckdb.sql('SELECT 9007199254740993::BIGINT AS id, [2, 3] AS values') -> {select: id, values}"
            )
            .query()
            .run()
        )
    expected = [{"id": 9007199254740993, "values": [2, 3]}]
    assert pa.table(result).to_pylist() == expected
    assert pl.DataFrame(result).to_dicts() == expected
    assert result.to_arrow().to_pylist() == result.to_pylist() == expected


def test_analysis_collections_are_tuples_and_optional_fields_are_none():
    parsed = pm.parse(ONE)
    with pm.connect() as connection:
        model = connection.model(ONE)
        inspection = model.inspect()
        checked = connection.check("run: missing")
    assert parsed.ok
    assert not checked.ok
    assert isinstance(parsed.symbols, tuple)
    assert isinstance(checked.diagnostics, tuple)
    assert isinstance(inspection.model.sources, tuple)
    assert inspection.reference is None
    assert inspection.import_ is None
    assert to_dict(checked)["diagnostics"][0]["code"] == "source-or-query-not-found"


@pytest.mark.parametrize("kind", ["path", "snapshot", "draft"])
def test_source_identity_rejects_conflicting_url(tmp_path, kind):
    path = tmp_path / "model.malloy"
    path.write_text(ONE)
    source = {
        "path": path,
        "snapshot": pm.ModelSource(path.as_uri(), ONE),
        "draft": pm.draft(ONE, url=path.as_uri()),
    }[kind]
    with pm.connect() as connection:
        with pytest.raises(ValueError, match="conflicts"):
            connection.model(source, url="memory://other/model.malloy")
        with pytest.raises(ValueError, match="conflicts"):
            connection.check(source, url="memory://other/model.malloy")
    with pytest.raises(ValueError, match="conflicts"):
        pm.parse(source, url="memory://other/model.malloy")


def test_syntax_only_cli_ignores_corrupt_database(tmp_path):
    source = tmp_path / "model.malloy"
    source.write_text("run: duckdb.table('absent.csv') -> {select: *}")
    database = tmp_path / "corrupt.duckdb"
    database.write_bytes(b"not a database")
    result = subprocess.run(
        [
            "pymalloy",
            "check",
            str(source),
            "--syntax-only",
            "--database",
            str(database),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["diagnostics"] == []


def test_cli_check_preserves_crlf_inside_sql_literal(tmp_path):
    source = tmp_path / "model.malloy"
    source.write_bytes(
        b'''run: duckdb.sql("""SELECT 'first\r\nsecond' AS value""") -> { select: missing }\r\n'''
    )
    with pm.connect() as connection:
        expected = to_dict(connection.check(source))
    result = subprocess.run(
        ["pymalloy", "check", str(source), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout) == expected


@pytest.mark.parametrize("failure", [False, True])
def test_finished_materialization_preserves_its_value_or_exception(
    monkeypatch, failure
):
    from threading import Event

    expired = Event()
    interrupt = duckdb.DuckDBPyConnection.interrupt
    materialize = duckdb.DuckDBPyConnection.to_arrow_table
    error = ValueError("materialization failed")

    def observe_interrupt(native):
        interrupt(native)
        expired.set()

    def finish(native, *args, **kwargs):
        table = materialize(native, *args, **kwargs)
        assert expired.wait(2), "The operation deadline must reach materialization"
        if failure:
            raise error
        return table

    with pm.connect() as connection:
        query = connection.model(ONE).query()
        query.sql()
        monkeypatch.setattr(duckdb.DuckDBPyConnection, "interrupt", observe_interrupt)
        monkeypatch.setattr(duckdb.DuckDBPyConnection, "to_arrow_table", finish)
        if failure:
            with pytest.raises(ValueError) as caught:
                query.run(timeout=0.5)
            assert caught.value is error
        else:
            assert query.run(timeout=0.5).to_pylist() == [{"value": 42}]


def test_parse_accepts_source_forms_with_duckdb_import_blocked(tmp_path):
    source = tmp_path / "model.malloy"
    source.write_text(ONE)
    program = """
import importlib.abc
import sys
from pathlib import Path
class CompilerOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "duckdb":
            raise AssertionError("parse opened the data runtime")
sys.meta_path.insert(0, CompilerOnly())
import pymalloy as pm
path = Path(sys.argv[1])
text = path.read_text()
for source in (text, path, pm.ModelSource(path.as_uri(), text), pm.draft(text, url=path.as_uri())):
    assert pm.parse(source).ok
"""
    result = subprocess.run(
        ["python", "-c", program, str(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_validation_preserves_diagnostics_from_metadata_failure(monkeypatch):
    with pm.connect() as connection:
        diagnostics = connection.check("run: missing").diagnostics
        candidate = pm.draft().sources(values=pm.sql("SELECT 42 AS value"))
        failure = pm.errors.CompilationError("Metadata failed", diagnostics=diagnostics)

        def inspect(_self, **_options):
            raise failure

        monkeypatch.setattr(pm.Model, "_inspect", inspect)
        report = connection.validate(candidate)
    assert not report.ok
    assert report.diagnostics[0].code == "source-or-query-not-found"
    assert report.error == "Metadata failed"
    assert report.draft.imports == {}


def test_models_serialize_engine_work_through_the_connection(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    entered = Event()
    release = Event()
    materialize = duckdb.DuckDBPyConnection.to_arrow_table

    def gate(native, *args, **kwargs):
        table = materialize(native, *args, **kwargs)
        entered.set()
        assert release.wait(5), "The active query must be released"
        return table

    with pm.connect() as connection:
        first = connection.model(ONE)
        second = connection.model(ONE)
        monkeypatch.setattr(duckdb.DuckDBPyConnection, "to_arrow_table", gate)
        with ThreadPoolExecutor(max_workers=1) as threads:
            active = threads.submit(first.query().run)
            try:
                assert entered.wait(5)
                with pytest.raises(TimeoutError, match="Waiting for the connection"):
                    second.query().run(timeout=0.05)
            finally:
                release.set()
            assert active.result(timeout=5).to_pylist() == [{"value": 42}]
        assert second.query().run().to_pylist() == [{"value": 42}]


def test_compiler_failure_closes_its_model_and_preserves_siblings(children):
    with pm.connect() as connection:
        first = connection.model(ONE)
        second = connection.model(ONE)
        children[0].kill()
        children[0].wait(timeout=5)
        with pytest.raises(pm.errors.CompilerError):
            first.query().run()
        assert first.closed
        assert not second.closed
        assert second.query().run().to_pylist() == [{"value": 42}]
        assert connection.duckdb.execute("SELECT 42").fetchone() == (42,)


def test_cli_run_encodes_decimal_temporal_and_exact_integer_values(tmp_path):
    source = tmp_path / "values.malloysql"
    source.write_text(
        ">>>sql connection:duckdb\n"
        "SELECT 1.2300::DECIMAL(12,4) AS amount, DATE '2026-01-02' AS day, "
        "TIMESTAMP '2026-01-02 03:04:05' AS moment, 9007199254740993::BIGINT AS id"
    )
    result = subprocess.run(
        ["pymalloy", "run", str(source)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        {
            "amount": "1.2300",
            "day": "2026-01-02",
            "moment": "2026-01-02 03:04:05",
            "id": 9007199254740993,
        }
    ]
