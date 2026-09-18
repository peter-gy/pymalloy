import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import duckdb
import polars as pl
import pytest

import pymalloy as pm
from pymalloy import CompilationError, ModelError

ONE = "run: duckdb.sql('SELECT 1 AS value') -> { select: value }"


def test_rows_preserve_native_scalar_types_and_huge_integers():
    result = pm.run('''run: duckdb.sql("""
SELECT 170141183460469231731687303715884105727::HUGEINT AS huge,
       '00000000-0000-0000-0000-000000000001'::UUID AS id,
       'abc'::BLOB AS payload, INTERVAL '2 days' AS duration
""") -> {select:*}''')
    assert result.rows() == [
        {
            "huge": 170141183460469231731687303715884105727,
            "id": UUID(int=1),
            "payload": b"abc",
            "duration": timedelta(days=2),
        }
    ]


def test_inline_model_and_registered_python_data():
    result = pm.run(
        """source: orders is duckdb.table('orders') extend { measure: revenue is amount.sum() }
run: orders -> { group_by: region aggregate: revenue order_by: region }""",
        tables={
            "orders": pl.DataFrame(
                {"region": ["North", "South", "North"], "amount": [30, 20, 50]}
            )
        },
    ).polars()
    assert result.to_dicts() == [
        {"region": "North", "revenue": 80},
        {"region": "South", "revenue": 20},
    ]


def test_reusable_model_observes_data_updates_and_detaches_results():
    connection = duckdb.connect()
    connection.execute("CREATE TABLE orders AS SELECT 'North' AS region, 30 AS amount")
    model = pm.model(
        """
source: orders is duckdb.table('orders') extend {
  view: totals is { group_by: region aggregate: revenue is amount.sum() order_by: region }
}
query: summary is orders -> totals
run: orders -> { aggregate: total is amount.sum() }
run: summary
""",
        connection=connection,
    )
    first = model.query().run().polars()
    assert first.to_dicts() == [{"region": "North", "revenue": 30}]
    model.connection.execute("INSERT INTO orders VALUES ('North', 50), ('South', 20)")
    assert model.query("summary").run().polars().to_dicts() == [
        {"region": "North", "revenue": 80},
        {"region": "South", "revenue": 20},
    ]
    assert (
        model.query("orders.totals").run().polars().equals(model.query().run().polars())
    )
    assert model.query("run:0").run().polars().item() == 100
    assert (
        model.query(malloy="run: orders -> { aggregate: n is count() }")
        .run()
        .polars()
        .item()
        == 3
    )
    assert first.to_dicts() == [{"region": "North", "revenue": 30}]


def test_givens_are_typed_and_scoped_to_each_query():
    model = pm.model(
        """
##! experimental.givens
given: regions :: string[] is ['North']
given: cutoff :: number is 10
source: orders is duckdb.sql("SELECT * FROM (VALUES ('North', 30), ('South', 20)) t(region, amount)")
run: orders -> { where: region in $regions and amount >= $cutoff select: region, amount order_by: region }
"""
    )
    assert model.query().run().polars().to_dicts() == [
        {"region": "North", "amount": 30}
    ]
    assert model.query().run(
        givens={"regions": ["South"], "cutoff": 15}
    ).polars().to_dicts() == [{"region": "South", "amount": 20}]
    assert (
        model.query()
        .run(givens={"regions": ["North", "South"], "cutoff": 99})
        .polars()
        .is_empty()
    )
    assert model.query().run().polars().to_dicts() == [
        {"region": "North", "amount": 30}
    ]
    with pytest.raises(CompilationError, match="givens.cutoff"):
        model.query().run(givens={"cutoff": "not a number"}).polars()
    assert model.query().run().polars().height == 1


def test_given_values_preserve_large_integers_dates_and_strings():
    model = pm.model(
        """
##! experimental.givens
given: n :: number is 1
given: label :: string is 'default'
given: day_value :: date is @2026-01-01
source: one is duckdb.sql('SELECT 1 AS x')
run: one -> { select: n is $n, label is $label, day_value is $day_value }
"""
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
        .polars()
        .to_dicts()[0]
    )
    assert row == {
        "n": 9007199254740993,
        "label": label,
        "day_value": date(2026, 9, 10),
    }
    assert (
        model.query().run(givens={"label": None}).polars().to_dicts()[0]["label"]
        is None
    )


def test_result_types_preserve_nested_data_nulls_and_precision():
    result = pm.run(
        """
source: values is duckdb.sql(\"\"\"
 SELECT 9007199254740993::BIGINT AS big,
        12345678901234567890.1234::DECIMAL(24,4) AS precise,
        DATE '2026-09-10' AS day_value,
        TIMESTAMPTZ '2026-09-10 12:34:56+00' AS instant,
        NULL::VARCHAR AS missing,
        [{'label': 'a', 'values': [1, NULL, 3]}] AS nested
\"\"\")
run: values -> { select: * }
"""
    ).polars()
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


def test_empty_results_keep_their_schema():
    result = pm.run(
        "run: duckdb.sql('SELECT 1::BIGINT id WHERE FALSE') -> { select: id }"
    ).polars()
    assert result.shape == (0, 1)
    assert result.schema == {"id": pl.Int64}


def test_record_and_aware_datetime_givens():
    model = pm.model(
        """
##! experimental.givens
given: cfg :: {label :: string, n :: number}
given: instant :: timestamptz
source: one is duckdb.sql('SELECT 1 AS x')
run: one -> {select: cfg is $cfg, instant is $instant}
"""
    )
    instant = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    assert model.query().run(
        givens={"cfg": {"label": "ok", "n": 9007199254740993}, "instant": instant}
    ).polars().to_dicts() == [
        {"cfg": {"label": "ok", "n": 9007199254740993}, "instant": instant}
    ]


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit])
def test_interrupt_during_schema_discovery_preserves_the_caller_connection(
    monkeypatch, interrupt
):
    execute = duckdb.DuckDBPyConnection.execute

    def interrupted(self, query, *args, **kwargs):
        if query.startswith("DESCRIBE"):
            raise interrupt()
        return execute(self, query, *args, **kwargs)

    monkeypatch.setattr(duckdb.DuckDBPyConnection, "execute", interrupted)
    with duckdb.connect() as connection:
        with pytest.raises(interrupt):
            pm.run(ONE, connection=connection)
        assert connection.execute("SELECT 42").fetchone() == (42,)


def test_inline_imports_do_not_shadow_physical_files(tmp_path):
    (tmp_path / "inline.malloy").write_text(
        "source: numbers is duckdb.sql('SELECT 42 AS value')"
    )
    model = pm.model(
        'import "inline.malloy"\nrun: numbers -> { select: value }',
        url=(Path(tmp_path) / "inline.malloy").as_uri(),
    )
    assert model.query().run().polars().item() == 42
    (tmp_path / "inline.malloy").unlink()
    with pytest.raises(CompilationError, match="inline.malloy"):
        pm.model(
            'import "inline.malloy"', url=(Path(tmp_path) / "inline.malloy").as_uri()
        )
    assert pm.run(ONE).polars().item() == 1


def test_model_reload_observes_new_schema_and_imports(tmp_path):
    data = tmp_path / "data.csv"
    data.write_text("value\n1\n")
    imported = tmp_path / "source.malloy"
    imported.write_text("source: numbers is duckdb.table('data.csv')")
    path = tmp_path / "main.malloy"
    path.write_text('import "source.malloy"\nrun: numbers -> { select: * }')
    first = pm.model(path, data_root=tmp_path)
    assert first.query().run().polars().columns == ["value"]
    data.write_text("value,other\n2,42\n")
    assert first.query().run().polars().to_dicts() == [{"value": 2}]
    with closing(pm.model(path, data_root=tmp_path)) as fresh:
        assert fresh.query().run().polars().to_dicts() == [{"value": 2, "other": 42}]
    imported.write_text("source: numbers is duckdb.sql('SELECT 99 AS replacement')")
    assert pm.model(path, data_root=tmp_path).query().run().polars().to_dicts() == [
        {"replacement": 99}
    ]


def test_borrowed_connection_preserves_state_and_transactions():
    with duckdb.connect() as connection:
        connection.execute("SET TimeZone='Asia/Tokyo'")
        connection.execute("SET VARIABLE data_root = 'caller value'")
        connection.execute("CREATE TEMP TABLE values_table AS SELECT 1 AS n")
        connection.begin()
        connection.execute("INSERT INTO values_table VALUES (2)")
        assert (
            pm.run(
                "run: duckdb.table('values_table') -> { aggregate: n is n.sum() }",
                connection=connection,
            )
            .polars()
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
        model = pm.model(ONE, connection=original if borrowed else None)
        connection = model.connection
        with pytest.raises(AttributeError):
            model.connection = replacement
        assert model.connection is connection
        assert model.run().rows() == [{"value": 1}]
        model.close()
        assert replacement.execute("SELECT 42").fetchone() == (42,)
        if borrowed:
            assert connection.execute("SELECT 42").fetchone() == (42,)
        else:
            with pytest.raises(duckdb.ConnectionException):
                connection.execute("SELECT 42")


def test_query_errors_leave_the_model_reusable():
    model = pm.model("source: bad_values is duckdb.sql(\"SELECT 'bad' AS text\")")
    with pytest.raises(CompilationError):
        model.query(malloy="run: undefined_source -> {select:missing}").run()
    with pytest.raises(duckdb.ConversionException):
        model.query(
            malloy="run: bad_values -> { select: parsed_number is text::number }"
        ).run()
    assert model.query(malloy="run: bad_values -> {select:text}").run().rows() == [
        {"text": "bad"}
    ]


def test_closed_model_invalidates_its_queries_and_preserves_other_models():
    model = pm.model(ONE)
    query = model.query()
    other = pm.model(ONE)
    model.close()
    model.close()
    with pytest.raises(ModelError, match="Model is closed"):
        query.run()
    assert model.closed
    assert other.run().rows() == [{"value": 1}]


def test_new_query_discovers_newly_registered_tables():
    model = pm.model(ONE)
    assert model.run().rows() == [{"value": 1}]
    model.connection.register("values.csv", pl.DataFrame({"n": [40, 2]}))
    assert model.query(
        malloy="run: duckdb.table('\"values.csv\"') -> {aggregate:total is n.sum()}"
    ).run().rows() == [{"total": 42}]


def test_models_isolate_data_roots(tmp_path):
    left, right = (tmp_path / "left", tmp_path / "right")
    left.mkdir()
    right.mkdir()
    (left / "data.csv").write_text("value\n10\n")
    (right / "data.csv").write_text("value\n20\n")
    source = "run: duckdb.table('data.csv') -> { select: value }"
    am, bm = (pm.model(source, data_root=left), pm.model(source, data_root=right))
    assert [
        am.query().run().polars().item(),
        bm.query().run().polars().item(),
        am.query().run().polars().item(),
    ] == [10, 20, 10]


def test_concurrent_queries_serialize_given_bindings():
    model = pm.model(
        """
##! experimental.givens
given: value :: number is 0
source: one is duckdb.sql('SELECT 1 AS x')
run: one -> { select: value is $value }
"""
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda n: model.query().run(givens={"value": n}).polars().item(),
                range(8),
            )
        )
    assert results == list(range(8))


def test_query_timeout_closes_model_and_preserves_borrowed_connection():
    with duckdb.connect() as connection:
        model = pm.model(
            """source: numbers is duckdb.sql('SELECT i FROM range(100000000000) t(i)')
run: numbers -> {aggregate:total is i.sum()}""",
            connection=connection,
        )
        with pytest.raises(TimeoutError, match="model closed"):
            model.run(timeout=0.5)
        assert model.closed
        with pytest.raises(ModelError):
            model.run()
        assert connection.execute("SELECT 42").fetchone() == (42,)


def test_one_shot_failure_preserves_the_borrowed_connection():
    with duckdb.connect() as connection:
        with pytest.raises(duckdb.ConversionException):
            pm.run(
                "run: duckdb.sql(\"SELECT 'bad' AS text\") -> { select: n is text::number }",
                connection=connection,
            )
        assert connection.execute("SELECT 42").fetchone() == (42,)


def test_model_rejects_ambiguous_query_selection():
    model = pm.model(ONE)
    with pytest.raises(ValueError, match="query name or Malloy text"):
        model.query("run:0", malloy=ONE).run().polars()
    with pytest.raises(ValueError, match="Choose a query"):
        model.query("missing").run().polars()
    assert model.query().run().polars().item() == 1


def test_waiting_query_timeout_preserves_the_active_model(monkeypatch):
    started, release = (threading.Event(), threading.Event())
    sql = duckdb.DuckDBPyConnection.execute

    def execute(self, *args, **kwargs):
        if args and str(args[0]).startswith(("SET ", "DESCRIBE ")):
            return sql(self, *args, **kwargs)
        started.set()
        if not release.wait(timeout=5):
            raise AssertionError("Active query was not released")
        return sql(self, *args, **kwargs)

    monkeypatch.setattr(duckdb.DuckDBPyConnection, "execute", execute)
    with ThreadPoolExecutor(max_workers=1) as pool:
        model = pm.model(ONE)
        active = pool.submit(lambda: model.query().run().polars())
        try:
            assert started.wait(timeout=5)
            with pytest.raises(TimeoutError, match="Waiting for the model"):
                model.query().run(timeout=0.05).polars()
            assert not model.closed
        finally:
            release.set()
        assert active.result(timeout=5).item() == 1
        assert model.query().run().polars().item() == 1


def test_unsearched_schema_table_does_not_mask_relative_data_file(tmp_path):
    (tmp_path / "orders.csv").write_text("amount\n42\n")
    with duckdb.connect() as connection:
        connection.execute(
            'CREATE SCHEMA secondary; CREATE TABLE secondary."orders.csv" AS SELECT 99 AS amount'
        )
        connection.execute("SET file_search_path = ?", [str(tmp_path)])
        assert pm.run(
            "run: duckdb.table('orders.csv') -> {select:amount}", connection=connection
        ).rows() == [{"amount": 42}]


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
            pm.run(
                "run: duckdb.table('\"orders.csv\"') -> { select: amount }",
                connection=connection,
            )
            .polars()
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
        assert pm.run(
            '''run: duckdb.sql("""SELECT * FROM query_table('"orders.csv"')""") -> { select:amount }''',
            connection=connection,
        ).rows() == [{"amount": 42}]


def test_missing_table_resolution_keeps_borrowed_transaction_available(tmp_path):
    (tmp_path / "orders.csv").write_text("amount\n42\n")
    with duckdb.connect() as connection:
        connection.execute("BEGIN")
        connection.execute("SET file_search_path = ?", [str(tmp_path)])
        assert (
            pm.run(
                "run: duckdb.table('orders.csv') -> { select: amount }",
                connection=connection,
            )
            .polars()
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
    model = pm.model("", data_root=tmp_path)
    for sql, expected in cases:
        source = f'source: numbers is duckdb.sql("""\n{sql}\n""")\nrun: numbers -> {{ select: value order_by: value }}'
        assert (
            model.query(malloy=source).run().polars()["value"].to_list() == expected
        ), sql


def test_compiler_memory_budget_releases_a_borrowed_connection():
    with duckdb.connect() as connection:
        with pytest.raises(ModelError, match="Compiler process stopped"):
            pm.model(ONE, connection=connection, compiler_memory_mb=1)
        assert connection.execute("SELECT 42").fetchone() == (42,)


def test_arrow_conversions_detach_nested_values_and_share_only_schema():
    first = pm.run(
        "run: duckdb.sql('SELECT 9007199254740993::BIGINT AS id, [1, 2] AS items') -> {select:*}"
    )
    second = pm.run(
        "run: duckdb.sql('SELECT 9007199254740994::BIGINT AS id, [3, 4] AS items') -> {select:*}"
    )
    arrow = first.arrow()
    rows = first.rows()
    rows[0]["items"].append(99)
    assert (
        arrow.to_pylist()
        == first.arrow().to_pylist()
        == [{"id": 9007199254740993, "items": [1, 2]}]
    )
    assert second.polars().to_dicts() == [{"id": 9007199254740994, "items": [3, 4]}]


@pytest.mark.parametrize("operation", [pm.model, pm.check])
def test_startup_and_compilation_share_one_deadline(monkeypatch, operation):
    from types import SimpleNamespace

    from pymalloy._server import api, runtime

    elapsed = 0
    clock = SimpleNamespace(monotonic=lambda: elapsed)
    start = runtime.Compiler.__init__

    def initialize(self, **options):
        nonlocal elapsed
        start(self, **options)
        elapsed = 3

    monkeypatch.setattr(api, "time", clock)
    monkeypatch.setattr(runtime, "time", clock)
    monkeypatch.setattr(runtime.Compiler, "__init__", initialize)
    with duckdb.connect() as connection:
        with pytest.raises(TimeoutError, match="deadline"):
            operation(ONE, connection=connection, timeout=2)
        assert connection.execute("SELECT 42").fetchone() == (42,)
