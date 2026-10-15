import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import polars as pl
import pyarrow as pa
import pytest

import pymalloy as pm
from pymalloy.errors import ClosedError, CompilationError

ONE = "run: duckdb.sql('SELECT 1 AS value') -> { select: value }"


def test_schema_discovery_rejects_additional_statements_before_execution():
    with duckdb.connect() as connection:
        report = pm.connect(database=connection).check(
            'source: numbers is duckdb.sql("SELECT 1 AS value; CREATE TABLE touched AS SELECT 2 AS value")'
        )
        assert not report.ok
        assert connection.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE table_name = 'touched'"
        ).fetchone() == (0,)


def test_rows_preserve_arrow_scalar_types_and_huge_integer_precision():
    result = (
        pm.connect()
        .model(
            "run: duckdb.sql(\"\"\"\nSELECT 170141183460469231731687303715884105727::HUGEINT AS huge,\n       '00000000-0000-0000-0000-000000000001'::UUID AS id,\n       'abc'::BLOB AS payload, INTERVAL '2 days' AS duration\n\"\"\") -> {select:*}"
        )
        .query()
        .run()
    )
    assert result.to_pylist() == [
        {
            "huge": Decimal(170141183460469231731687303715884105727),
            "id": "00000000-0000-0000-0000-000000000001",
            "payload": b"abc",
            "duration": pa.MonthDayNano((0, 2, 0)),
        }
    ]


def test_inline_model_and_captured_python_data():
    frame = pl.DataFrame(
        {"region": ["North", "South", "North"], "amount": [30, 20, 50]}
    )
    draft = (
        pm.draft()
        .define(
            orders=pm.data(frame).extend(pm.measure(revenue=pm.col("amount").sum()))
        )
        .queries(
            totals=pm.ref("orders").pipe(
                pm.query(
                    pm.group_by(pm.col("region")),
                    pm.aggregate(pm.col("revenue")),
                    pm.order_by(pm.col("region")),
                )
            )
        )
    )
    assert pm.connect().model(draft).query().run().to_polars().to_dicts() == [
        {"region": "North", "revenue": 80},
        {"region": "South", "revenue": 20},
    ]


def test_reusable_model_observes_data_updates_and_detaches_results():
    connection = duckdb.connect()
    connection.execute("CREATE TABLE orders AS SELECT 'North' AS region, 30 AS amount")
    native = pm.connect(database=connection)
    model = native.model(
        "\nsource: orders is duckdb.table('orders') extend {\n  view: totals is { group_by: region aggregate: revenue is amount.sum() order_by: region }\n}\nquery: summary is orders -> totals\nrun: orders -> { aggregate: total is amount.sum() }\nrun: summary\n"
    )
    first = model.query().run().to_polars()
    assert first.to_dicts() == [{"region": "North", "revenue": 30}]
    native.duckdb.execute("INSERT INTO orders VALUES ('North', 50), ('South', 20)")
    assert model.query("summary").run().to_polars().to_dicts() == [
        {"region": "North", "revenue": 80},
        {"region": "South", "revenue": 20},
    ]
    assert (
        model.query("orders.totals")
        .run()
        .to_polars()
        .equals(model.query().run().to_polars())
    )
    assert model.query("run:0").run().to_polars().item() == 100
    assert (
        model.query(malloy="run: orders -> { aggregate: n is count() }")
        .run()
        .to_polars()
        .item()
        == 3
    )
    assert first.to_dicts() == [{"region": "North", "revenue": 30}]


def test_givens_are_typed_and_scoped_to_each_query():
    model = pm.connect().model(
        "\n##! experimental.givens\ngiven: regions :: string[] is ['North']\ngiven: cutoff :: number is 10\nsource: orders is duckdb.sql(\"SELECT * FROM (VALUES ('North', 30), ('South', 20)) t(region, amount)\")\nrun: orders -> { where: region in $regions and amount >= $cutoff select: region, amount order_by: region }\n"
    )
    assert model.query().run().to_polars().to_dicts() == [
        {"region": "North", "amount": 30}
    ]
    assert model.query().run(
        givens={"regions": ["South"], "cutoff": 15}
    ).to_polars().to_dicts() == [{"region": "South", "amount": 20}]
    assert (
        model.query()
        .run(givens={"regions": ["North", "South"], "cutoff": 99})
        .to_polars()
        .is_empty()
    )
    assert model.query().run().to_polars().to_dicts() == [
        {"region": "North", "amount": 30}
    ]
    with pytest.raises(CompilationError, match="givens.cutoff"):
        model.query().run(givens={"cutoff": "not a number"}).to_polars()
    assert model.query().run().to_polars().height == 1


def test_given_values_preserve_large_integers_dates_and_strings():
    model = pm.connect().model(
        "\n##! experimental.givens\ngiven: n :: number is 1\ngiven: label :: string is 'default'\ngiven: day_value :: date is @2026-01-01\nsource: one is duckdb.sql('SELECT 1 AS x')\nrun: one -> { select: n is $n, label is $label, day_value is $day_value }\n"
    )
    label = "a' ; DROP TABLE one; -- {text}"
    row = (
        model.query()
        .run(
            givens={
                "n": 9007199254740993,
                "label": label,
                "day_value": date(2026, 9, 10),
            }
        )
        .to_polars()
        .to_dicts()[0]
    )
    assert row == {
        "n": 9007199254740993,
        "label": label,
        "day_value": date(2026, 9, 10),
    }
    assert (
        model.query().run(givens={"label": None}).to_polars().to_dicts()[0]["label"]
        is None
    )


def test_result_types_preserve_nested_data_nulls_and_precision():
    result = (
        pm.connect()
        .model(
            "\nsource: values is duckdb.sql(\"\"\"\n SELECT 9007199254740993::BIGINT AS big,\n        12345678901234567890.1234::DECIMAL(24,4) AS precise,\n        DATE '2026-09-10' AS day_value,\n        TIMESTAMPTZ '2026-09-10 12:34:56+00' AS instant,\n        NULL::VARCHAR AS missing,\n        [{'label': 'a', 'values': [1, NULL, 3]}] AS nested\n\"\"\")\nrun: values -> { select: * }\n"
        )
        .query()
        .run()
        .to_polars()
    )
    assert result.to_dicts() == [
        {
            "big": 9007199254740993,
            "precise": Decimal("12345678901234567890.1234"),
            "day_value": date(2026, 9, 10),
            "instant": datetime(2026, 9, 10, 12, 34, 56, tzinfo=UTC),
            "missing": None,
            "nested": [{"label": "a", "values": [1, None, 3]}],
        }
    ]


def test_record_and_aware_datetime_givens():
    model = pm.connect().model(
        "\n##! experimental.givens\ngiven: cfg :: {label :: string, n :: number}\ngiven: instant :: timestamptz\nsource: one is duckdb.sql('SELECT 1 AS x')\nrun: one -> {select: cfg is $cfg, instant is $instant}\n"
    )
    instant = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    assert model.query().run(
        givens={"cfg": {"label": "ok", "n": 9007199254740993}, "instant": instant}
    ).to_polars().to_dicts() == [
        {"cfg": {"label": "ok", "n": 9007199254740993}, "instant": instant}
    ]


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit])
def test_interrupt_during_schema_discovery_preserves_the_caller_connection(
    monkeypatch, interrupt
):
    execute = duckdb.DuckDBPyConnection.execute

    def interrupted(self, query, *args, **kwargs):
        text = query.query if isinstance(query, duckdb.Statement) else query
        if text.startswith("DESCRIBE"):
            raise interrupt()
        return execute(self, query, *args, **kwargs)

    monkeypatch.setattr(duckdb.DuckDBPyConnection, "execute", interrupted)
    with duckdb.connect() as connection:
        with pytest.raises(interrupt):
            pm.connect(database=connection).model(ONE).query().run()
        assert connection.execute("SELECT 42").fetchone() == (42,)


def test_inline_imports_do_not_shadow_physical_files(tmp_path):
    (tmp_path / "inline.malloy").write_text(
        "source: numbers is duckdb.sql('SELECT 42 AS value')"
    )
    model = pm.connect().model(
        'import "inline.malloy"\nrun: numbers -> { select: value }',
        url=(Path(tmp_path) / "inline.malloy").as_uri(),
    )
    assert model.query().run().to_polars().item() == 42
    (tmp_path / "inline.malloy").unlink()
    with pytest.raises(CompilationError, match="inline.malloy"):
        pm.connect().model(
            'import "inline.malloy"', url=(Path(tmp_path) / "inline.malloy").as_uri()
        )
    assert pm.connect().model(ONE).query().run().to_polars().item() == 1


def test_model_reload_observes_new_schema_and_imports(tmp_path):
    data = tmp_path / "data.csv"
    data.write_text("value\n1\n")
    imported = tmp_path / "source.malloy"
    imported.write_text("source: numbers is duckdb.table('data.csv')")
    path = tmp_path / "main.malloy"
    path.write_text('import "source.malloy"\nrun: numbers -> { select: * }')
    first = pm.connect(data_root=tmp_path).model(path)
    assert first.query().run().to_polars().columns == ["value"]
    data.write_text("value,other\n2,42\n")
    assert first.query().run().to_polars().to_dicts() == [{"value": 2}]
    with closing(pm.connect(data_root=tmp_path).model(path)) as fresh:
        assert fresh.query().run().to_polars().to_dicts() == [{"value": 2, "other": 42}]
    imported.write_text("source: numbers is duckdb.sql('SELECT 99 AS replacement')")
    assert pm.connect(data_root=tmp_path).model(
        path
    ).query().run().to_polars().to_dicts() == [{"replacement": 99}]


def test_borrowed_connection_preserves_state_and_transactions():
    with duckdb.connect() as connection:
        connection.execute("SET TimeZone='Asia/Tokyo'")
        connection.execute("SET VARIABLE data_root = 'caller value'")
        connection.execute("CREATE TEMP TABLE values_table AS SELECT 1 AS n")
        connection.begin()
        connection.execute("INSERT INTO values_table VALUES (2)")
        assert (
            pm.connect(database=connection)
            .model("run: duckdb.table('values_table') -> { aggregate: n is n.sum() }")
            .query()
            .run()
            .to_polars()
            .item()
            == 3
        )
        assert connection.execute(
            "SELECT current_setting('TimeZone'), getvariable('data_root')"
        ).fetchone() == ("Asia/Tokyo", "caller value")
        connection.rollback()
        assert connection.execute("SELECT SUM(n) FROM values_table").fetchone() == (1,)


@pytest.mark.parametrize("borrowed", [False, True])
def test_model_connection_identity_and_ownership_are_fixed(borrowed):
    with duckdb.connect() as original, duckdb.connect() as replacement:
        native = pm.connect(database=original if borrowed else ":memory:")
        model = native.model(ONE)
        connection = native.duckdb
        with pytest.raises(AttributeError):
            native.duckdb = replacement
        assert native.duckdb is connection
        assert model.query().run().to_pylist() == [{"value": 1}]
        model.close()
        assert connection.execute("SELECT 42").fetchone() == (42,)
        native.close()
        assert replacement.execute("SELECT 42").fetchone() == (42,)
        if borrowed:
            assert connection.execute("SELECT 42").fetchone() == (42,)
        else:
            with pytest.raises(duckdb.ConnectionException):
                connection.execute("SELECT 42")


def test_query_errors_leave_the_model_reusable():
    model = pm.connect().model(
        "source: bad_values is duckdb.sql(\"SELECT 'bad' AS text\")"
    )
    with pytest.raises(CompilationError):
        model.query(malloy="run: undefined_source -> {select:missing}").run()
    with pytest.raises(pm.errors.ExecutionError):
        model.query(
            malloy="run: bad_values -> { select: parsed_number is text::number }"
        ).run()
    assert model.query(malloy="run: bad_values -> {select:text}").run().to_pylist() == [
        {"text": "bad"}
    ]


def test_closed_model_invalidates_its_queries_and_preserves_other_models():
    model = pm.connect().model(ONE)
    query = model.query()
    other = pm.connect().model(ONE)
    model.close()
    model.close()
    with pytest.raises(ClosedError, match="Model is closed"):
        query.run()
    assert model.closed
    assert other.query().run().to_pylist() == [{"value": 1}]


def test_new_query_discovers_newly_registered_tables():
    native = pm.connect()
    model = native.model(ONE)
    assert model.query().run().to_pylist() == [{"value": 1}]
    native.duckdb.register("values.csv", pl.DataFrame({"n": [40, 2]}))
    assert model.query(
        malloy="run: duckdb.table('\"values.csv\"') -> {aggregate:total is n.sum()}"
    ).run().to_pylist() == [{"total": 42}]


def test_models_isolate_data_roots(tmp_path):
    left, right = (tmp_path / "left", tmp_path / "right")
    left.mkdir()
    right.mkdir()
    (left / "data.csv").write_text("value\n10\n")
    (right / "data.csv").write_text("value\n20\n")
    source = "run: duckdb.table('data.csv') -> { select: value }"
    am, bm = (
        pm.connect(data_root=left).model(source),
        pm.connect(data_root=right).model(source),
    )
    assert [
        am.query().run().to_polars().item(),
        bm.query().run().to_polars().item(),
        am.query().run().to_polars().item(),
    ] == [10, 20, 10]


def test_concurrent_queries_serialize_given_bindings():
    model = pm.connect().model(
        "\n##! experimental.givens\ngiven: value :: number is 0\nsource: one is duckdb.sql('SELECT 1 AS x')\nrun: one -> { select: value is $value }\n"
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda n: model.query().run(givens={"value": n}).to_polars().item(),
                range(8),
            )
        )
    assert results == list(range(8))


def test_query_timeout_preserves_model_and_borrowed_connection():
    with duckdb.connect() as connection:
        model = pm.connect(database=connection).model(
            "source: numbers is duckdb.sql('SELECT i FROM range(100000000000) t(i)')\nrun: numbers -> {aggregate:total is i.sum()}"
        )
        with pytest.raises(TimeoutError, match="exceeded"):
            model.query().run(timeout=0.5)
        assert not model.closed
        assert model.query(malloy=ONE).run().to_pylist() == [{"value": 1}]
        model.close()
        assert connection.execute("SELECT 42").fetchone() == (42,)


def test_one_shot_failure_preserves_the_borrowed_connection():
    with duckdb.connect() as connection:
        with pytest.raises(pm.errors.ExecutionError):
            pm.connect(database=connection).model(
                "run: duckdb.sql(\"SELECT 'bad' AS text\") -> { select: n is text::number }"
            ).query().run()
        assert connection.execute("SELECT 42").fetchone() == (42,)


def test_model_rejects_ambiguous_query_selection():
    model = pm.connect().model(ONE)
    with pytest.raises(ValueError, match="query selection or Malloy text"):
        model.query("run:0", malloy=ONE).run().to_polars()
    with pytest.raises(ValueError, match="Choose a query"):
        model.query("missing").run().to_polars()
    assert model.query().run().to_polars().item() == 1


def test_waiting_query_timeout_preserves_the_active_model(monkeypatch):
    model = pm.connect().model(ONE)
    started, release = (threading.Event(), threading.Event())
    sql = duckdb.DuckDBPyConnection.execute

    def execute(self, *args, **kwargs):
        started.set()
        if not release.wait(timeout=5):
            raise AssertionError("Active query was not released")
        return sql(self, *args, **kwargs)

    monkeypatch.setattr(duckdb.DuckDBPyConnection, "execute", execute)
    with ThreadPoolExecutor(max_workers=1) as pool:
        active = pool.submit(lambda: model.query().run().to_polars())
        try:
            assert started.wait(timeout=5)
            with pytest.raises(TimeoutError, match="Waiting for the connection"):
                model.query().run(timeout=0.05).to_polars()
            assert not model.closed
        finally:
            release.set()
        assert active.result(timeout=5).item() == 1
        assert model.query().run().to_polars().item() == 1


def test_unsearched_schema_table_does_not_mask_relative_data_file(tmp_path):
    (tmp_path / "orders.csv").write_text("amount\n42\n")
    with duckdb.connect() as connection:
        connection.execute(
            'CREATE SCHEMA secondary; CREATE TABLE secondary."orders.csv" AS SELECT 99 AS amount'
        )
        connection.execute("SET file_search_path = ?", [str(tmp_path)])
        assert pm.connect(database=connection).model(
            "run: duckdb.table('orders.csv') -> {select:amount}"
        ).query().run().to_pylist() == [{"amount": 42}]


def test_search_path_resolves_case_insensitive_filename_tables_in_borrowed_transaction(
    tmp_path,
):
    with duckdb.connect() as connection:
        connection.execute(
            'CREATE SCHEMA secondary; CREATE TABLE secondary."ORDERS.CSV" AS SELECT 42 AS amount'
        )
        connection.execute("SET search_path='main,secondary'")
        connection.execute("BEGIN")
        connection.execute("SET file_search_path = ?", [str(tmp_path)])
        assert (
            pm.connect(database=connection)
            .model("run: duckdb.table('\"orders.csv\"') -> { select: amount }")
            .query()
            .run()
            .to_polars()
            .item()
            == 42
        )
        connection.execute('INSERT INTO secondary."ORDERS.CSV" VALUES (10)')
        connection.execute("ROLLBACK")
        assert connection.execute(
            'SELECT amount FROM secondary."ORDERS.CSV"'
        ).fetchall() == [(42,)]


def test_query_table_uses_quoted_database_identifiers_and_search_path():
    with duckdb.connect() as connection:
        connection.execute(
            'CREATE SCHEMA secondary; CREATE TABLE secondary."ORDERS.CSV" AS SELECT 42 AS amount'
        )
        connection.execute("SET search_path='main,secondary'")
        assert pm.connect(database=connection).model(
            'run: duckdb.sql("""SELECT * FROM query_table(\'"orders.csv"\')""") -> { select:amount }'
        ).query().run().to_pylist() == [{"amount": 42}]


def test_missing_table_resolution_keeps_borrowed_transaction_available(tmp_path):
    (tmp_path / "orders.csv").write_text("amount\n42\n")
    with duckdb.connect() as connection:
        connection.execute("BEGIN")
        connection.execute("SET file_search_path = ?", [str(tmp_path)])
        assert (
            pm.connect(database=connection)
            .model("run: duckdb.table('orders.csv') -> { select: amount }")
            .query()
            .run()
            .to_polars()
            .item()
            == 42
        )
        assert connection.execute("SELECT 1").fetchall() == [(1,)]
        connection.execute("ROLLBACK")


def test_file_resolution_preserves_duckdb_scope_recursion_and_case(tmp_path):
    (tmp_path / "orders.csv").write_text("value\n42\n")
    (tmp_path / "ä.csv").write_text("value\n42\n")
    cases = [
        ('WITH "Orders.CSV" AS (SELECT 1 AS value) SELECT * FROM "orders.csv"', [1]),
        ('WITH "Ä.csv" AS (SELECT 1 AS value) SELECT * FROM "ä.csv"', [42]),
        (
            """WITH RECURSIVE "orders.csv" AS (SELECT * FROM 'orders.csv'
UNION ALL SELECT value + 1 FROM "orders.csv" WHERE value < 44)
SELECT * FROM "orders.csv\"""",
            [42, 43, 44],
        ),
        (
            """SELECT * FROM "orders.csv" UNION ALL
SELECT * FROM (WITH "orders.csv" AS (SELECT 1 AS value) SELECT * FROM "orders.csv")""",
            [1, 42],
        ),
    ]
    model = pm.connect(data_root=tmp_path).model("")
    for sql, expected in cases:
        source = f'source: numbers is duckdb.sql("""\n{sql}\n""")\nrun: numbers -> {{ select: value order_by: value }}'
        assert (
            model.query(malloy=source).run().to_polars()["value"].to_list() == expected
        ), sql


def test_compiler_memory_budget_releases_a_borrowed_connection():
    with duckdb.connect() as connection:
        with pytest.raises(pm.errors.CompilerError, match="Compiler process stopped"):
            pm.connect(database=connection, compiler_memory_mb=1).model(ONE)
        assert connection.execute("SELECT 42").fetchone() == (42,)


def test_model_context_releases_owned_resources_and_preserves_borrowed_transaction():
    with pm.connect().model(ONE) as owned:
        result = owned.query().run()
    assert owned.closed
    assert result.to_pylist() == [{"value": 1}]
    with pytest.raises(ClosedError, match="closed"), owned:
        pass

    with duckdb.connect() as connection:
        connection.execute("BEGIN")
        connection.execute("CREATE TABLE retained AS SELECT 42 AS value")
        with (
            pytest.raises(ValueError, match="caller failure"),
            pm.connect(database=connection).model(ONE) as borrowed,
        ):
            raise ValueError("caller failure")
        assert borrowed.closed
        assert connection.execute("SELECT * FROM retained").fetchall() == [(42,)]
        connection.execute("ROLLBACK")
        assert not connection.execute("SHOW TABLES").fetchall()


def test_connection_name_is_shared_by_authoring_check_and_execution():
    draft = (
        pm.draft()
        .define(values=pm.sql("SELECT 42 AS amount", connection="analytics"))
        .queries(answer=pm.ref("values").pipe(pm.query(pm.select(pm.col("amount")))))
    )
    assert pm.connect(name="analytics").check(draft).ok
    assert (
        pm.connect(name="analytics").validate(draft).require_valid().connection_name
        == "analytics"
    )
    with pm.connect(name="analytics").model(draft) as model:
        assert model.query().run().to_pylist() == [{"amount": 42}]
    with pytest.raises(ValueError, match="name"):
        pm.connect(name="").model(draft)


def test_deadline_between_parsing_and_execution_interrupts_only_that_operation(
    monkeypatch,
):
    interrupted = threading.Event()
    watchdog_fired = threading.Event()
    extract = duckdb.DuckDBPyConnection.extract_statements
    interrupt = duckdb.DuckDBPyConnection.interrupt
    native = pm.connect()
    with native.model(
        "run: duckdb.sql('SELECT i FROM range(100000000000) t(i)') -> { aggregate: total is i.sum() }"
    ) as model:
        connection = native.duckdb

        def wait_after_parsing(self, sql):
            statements = extract(self, sql)
            assert interrupted.wait(2), "Operation deadline did not interrupt"
            return statements

        def observe_interrupt(self):
            interrupt(self)
            interrupted.set()

        def rescue():
            watchdog_fired.set()
            interrupt(connection)

        monkeypatch.setattr(
            duckdb.DuckDBPyConnection, "extract_statements", wait_after_parsing
        )
        monkeypatch.setattr(duckdb.DuckDBPyConnection, "interrupt", observe_interrupt)
        watchdog = threading.Timer(3, rescue)
        watchdog.start()
        try:
            with pytest.raises(TimeoutError, match="exceeded"):
                model.query().run(timeout=0.05)
        finally:
            watchdog.cancel()
            watchdog.join()
        assert not watchdog_fired.is_set(), "Query escaped its operation deadline"
        monkeypatch.setattr(duckdb.DuckDBPyConnection, "extract_statements", extract)
        assert model.query(malloy=ONE).run().to_pylist() == [{"value": 1}]


def test_inline_source_identity_matches_drafts_and_preserves_import_base(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "shared.malloy").write_text(
        "source: values is duckdb.sql('SELECT 42 amount')"
    )
    source = 'import "shared.malloy"\nrun: values -> { select: amount }'
    expected = (tmp_path / "model.malloy").as_uri()
    assert pm.draft(source).url == pm.read_model(source).url == expected
    with pm.connect(data_root=tmp_path).model(source) as model:
        snapshot = model.source()
        assert snapshot.url == expected
        assert snapshot.document_kind == "model"
        assert model.query().run().to_pylist() == [{"amount": 42}]


def test_explicit_document_kind_survives_snapshot_replay_and_overrides_suffix():
    notebook = ">>>sql connection:duckdb\nSELECT 42 AS answer\n"
    url = "memory://test/analysis.txt"
    assert pm.connect().check(notebook, url=url, document_kind="notebook").ok
    assert not pm.parse(notebook, url=url, document_kind="notebook").diagnostics
    with pm.connect().model(notebook, url=url, document_kind="notebook") as model:
        captured = model.source()
        assert captured.document_kind == "notebook"
        assert model.query().run().to_pylist() == [{"answer": 42}]
    assert pm.connect().model(captured).query().run().to_pylist() == [{"answer": 42}]
    plain = pm.ModelSource("memory://test/plain.malloynb", ONE, document_kind="model")
    assert pm.connect().model(plain).query().run().to_pylist() == [{"value": 1}]
    assert pm.connect().model(
        ONE, url=plain.url, document_kind="model"
    ).query().run().to_pylist() == [{"value": 1}]
    assert pm.connect().model(
        pm.draft(ONE, url=plain.url)
    ).query().run().to_pylist() == [{"value": 1}]
    with pytest.raises(ValueError, match="document_kind"):
        pm.connect().model(ONE, document_kind="unknown")


def test_timestamp_rows_use_bundled_zoneinfo_data_without_a_system_database():
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            "\nimport zoneinfo\nimport pymalloy as pm\nzoneinfo.reset_tzpath([])\nzoneinfo.ZoneInfo.clear_cache()\nresult = pm.connect().model('run: duckdb.sql(\"SELECT TIMESTAMPTZ \\'2026-01-01 12:00:00+00\\' AS moment\") -> { select: moment }').query().run()\nvalue = result.to_pylist()[0][\"moment\"]\nassert value.hour == 12\nassert isinstance(value.tzinfo, zoneinfo.ZoneInfo)\n",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_native_config_preserves_explicit_settings_and_borrowed_ownership(tmp_path):
    (tmp_path / "configured.csv").write_text("amount\n42\n")
    source = "run: duckdb.table('configured.csv') -> { select: amount }"
    config = {
        "TimeZone": "America/New_York",
        "File_Search_Path": str(tmp_path),
        "threads": 1,
    }
    assert pm.connect(config=config).check(source).ok
    native = pm.connect(config=config)
    with native.model(source) as model:
        assert model.query().run().to_pylist() == [{"amount": 42}]
        assert native.duckdb.execute(
            "SELECT current_setting('timezone'), current_setting('threads'), current_setting('file_search_path')"
        ).fetchone() == ("America/New_York", 1, str(tmp_path))
    assert config == {
        "TimeZone": "America/New_York",
        "File_Search_Path": str(tmp_path),
        "threads": 1,
    }
    with pytest.raises(ValueError, match="Choose data_root"):
        pm.connect(data_root=tmp_path, config=config).model(ONE)
    with duckdb.connect() as connection:
        connection.execute("BEGIN")
        connection.execute("CREATE TABLE retained AS SELECT 42 AS value")
        with pytest.raises(ValueError, match="Borrowed connections"):
            pm.connect(database=connection, config={}).model(ONE)
        assert connection.execute("SELECT * FROM retained").fetchone() == (42,)
        connection.execute("ROLLBACK")


def test_native_config_restricts_external_reads_before_schema_discovery(tmp_path):
    allowed = tmp_path / "allowed.csv"
    denied = tmp_path / "denied.csv"
    allowed.write_text("amount\n42\n")
    denied.write_text("amount\n99\n")
    config = {
        "allowed_paths": [str(allowed)],
        "enable_external_access": False,
        "lock_configuration": True,
    }
    source = f"run: duckdb.table('{allowed}') -> {{ select: amount }}"
    with pm.connect(config=config).model(source) as model:
        assert model.query().run().to_pylist() == [{"amount": 42}]
        with pytest.raises(CompilationError, match="disabled|Permission"):
            model.query(
                malloy=f"run: duckdb.table('{denied}') -> {{ select: amount }}"
            ).run()
        assert model.query().run().to_pylist() == [{"amount": 42}]
    report = pm.connect(config=config).check(
        f"run: duckdb.table('{denied}') -> {{ select: amount }}"
    )
    assert not report.ok


def test_declared_extensions_initialize_before_external_access_restrictions(tmp_path):
    source = """run: duckdb.sql("SELECT json_array_length('[1, 2, 3]')::BIGINT AS n") -> { select: n }"""
    config = {
        "secret_directory": str(tmp_path / "secrets"),
        "autoload_known_extensions": False,
        "autoinstall_known_extensions": False,
        "enable_external_access": False,
        "lock_configuration": True,
    }
    assert pm.connect(extensions=("icu", "json"), config=config).check(source).ok
    assert pm.connect(extensions=("icu", "json"), config=config).model(
        source
    ).query().run().to_pylist() == [{"n": 3}]
    with duckdb.connect() as connection:
        with pytest.raises(ValueError, match="Borrowed connections"):
            pm.connect(database=connection, extensions=("json",)).model(ONE)
        assert connection.execute("SELECT 42").fetchone() == (42,)


@pytest.mark.parametrize(
    "operation",
    [
        lambda source, **kw: pm.connect(**kw).model(source),
        lambda source, **kw: pm.connect(**kw).check(source),
    ],
)
def test_extension_initialization_shares_the_startup_deadline(monkeypatch, operation):
    connections = []
    statements = []
    execute = duckdb.DuckDBPyConnection.execute
    watchdog_fired = threading.Event()

    def observed_execute(self, sql, *args, **kwargs):
        statements.append(sql)
        return execute(self, sql, *args, **kwargs)

    def install(self, extension):
        connections.append(self)
        self.execute("SELECT sum(i) FROM range(100000000000) t(i)")

    def rescue():
        watchdog_fired.set()
        for connection in connections:
            connection.interrupt()

    monkeypatch.setattr(duckdb.DuckDBPyConnection, "install_extension", install)
    monkeypatch.setattr(duckdb.DuckDBPyConnection, "execute", observed_execute)
    watchdog = threading.Timer(3, rescue)
    watchdog.start()
    try:
        with pytest.raises(TimeoutError, match="startup.*deadline"):
            operation(ONE, extensions=("json",), timeout=0.05)
    finally:
        watchdog.cancel()
        watchdog.join()
    assert not watchdog_fired.is_set(), "Extension setup escaped its deadline"
    assert not any(sql.startswith("DESCRIBE ") for sql in statements)
    assert len(connections) == 1
    with pytest.raises(duckdb.ConnectionException, match="closed"):
        connections[0].execute("SELECT 1")
