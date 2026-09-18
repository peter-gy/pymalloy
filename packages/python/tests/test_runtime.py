import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal

import duckdb
import polars as pl
import pytest

from pymalloy.server import CompilationError, Session, SessionError

ONE = "run: duckdb.sql('SELECT 1 AS value') -> { select: value }"


def test_inline_model_and_registered_python_data():
    with Session() as session:
        session.connection.register(
            "orders",
            pl.DataFrame(
                {
                    "region": ["North", "South", "North"],
                    "amount": [30, 20, 50],
                }
            ),
        )
        result = session.run("""
source: orders is duckdb.table('orders') extend { measure: revenue is amount.sum() }
run: orders -> { group_by: region aggregate: revenue order_by: region }
""")
    assert result.to_dicts() == [
        {"region": "North", "revenue": 80},
        {"region": "South", "revenue": 20},
    ]


def test_reusable_model_observes_data_updates_and_detaches_results():
    with Session() as session:
        session.connection.execute(
            "CREATE TABLE orders AS SELECT 'North' AS region, 30 AS amount"
        )
        model = session.model("""
source: orders is duckdb.table('orders') extend {
  view: totals is { group_by: region aggregate: revenue is amount.sum() order_by: region }
}
query: summary is orders -> totals
run: orders -> { aggregate: total is amount.sum() }
run: summary
""")
        first = model.run()
        assert first.to_dicts() == [{"region": "North", "revenue": 30}]
        session.connection.execute(
            "INSERT INTO orders VALUES ('North', 50), ('South', 20)"
        )
        assert model.run(query="summary").to_dicts() == [
            {"region": "North", "revenue": 80},
            {"region": "South", "revenue": 20},
        ]
        assert model.run(query="orders.totals").equals(model.run())
        assert model.run(query="run:1").item() == 100
        assert model.run("run: orders -> { aggregate: n is count() }").item() == 3
        assert first.to_dicts() == [{"region": "North", "revenue": 30}]


def test_givens_are_typed_and_scoped_to_each_query():
    with Session() as session:
        model = session.model("""
##! experimental.givens
given: regions :: string[] is ['North']
given: cutoff :: number is 10
source: orders is duckdb.sql("SELECT * FROM (VALUES ('North', 30), ('South', 20)) t(region, amount)")
run: orders -> { where: region in $regions and amount >= $cutoff select: region, amount order_by: region }
""")
        assert model.run().to_dicts() == [{"region": "North", "amount": 30}]
        assert model.run(givens={"regions": ["South"], "cutoff": 15}).to_dicts() == [
            {"region": "South", "amount": 20}
        ]
        assert model.run(
            givens={"regions": ["North", "South"], "cutoff": 99}
        ).is_empty()
        assert model.run().to_dicts() == [{"region": "North", "amount": 30}]
        with pytest.raises(CompilationError, match="givens.cutoff"):
            model.run(givens={"cutoff": "not a number"})
        assert model.run().height == 1


def test_given_values_preserve_large_integers_dates_and_strings():
    with Session() as session:
        model = session.model("""
##! experimental.givens
given: n :: number is 1
given: label :: string is 'default'
given: day_value :: date is @2026-01-01
source: one is duckdb.sql('SELECT 1 AS x')
run: one -> { select: n is $n, label is $label, day_value is $day_value }
""")
        label = "a' ; DROP TABLE one; -- {text}"
        row = model.run(
            givens={
                "n": 9007199254740993,
                "label": label,
                "day_value": date(2026, 9, 10),
            }
        ).to_dicts()[0]
        assert row == {
            "n": 9007199254740993,
            "label": label,
            "day_value": date(2026, 9, 10),
        }
        assert model.run(givens={"label": None}).to_dicts()[0]["label"] is None


def test_result_types_preserve_nested_data_nulls_and_precision():
    with Session() as session:
        result = session.run('''
source: values is duckdb.sql("""
 SELECT 9007199254740993::BIGINT AS big,
        12345678901234567890.1234::DECIMAL(24,4) AS precise,
        DATE '2026-09-10' AS day_value,
        TIMESTAMPTZ '2026-09-10 12:34:56+00' AS instant,
        NULL::VARCHAR AS missing,
        [{'label': 'a', 'values': [1, NULL, 3]}] AS nested
""")
run: values -> { select: * }
''')
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
    with Session() as session:
        result = session.run(
            "run: duckdb.sql('SELECT 1::BIGINT id WHERE FALSE') -> { select: id }"
        )
    assert result.shape == (0, 1)
    assert result.schema == {"id": pl.Int64}


def test_record_and_aware_datetime_givens():
    with Session() as session:
        model = session.model("""
##! experimental.givens
given: cfg :: {label :: string, n :: number}
given: instant :: timestamptz
source: one is duckdb.sql('SELECT 1 AS x')
run: one -> {select: cfg is $cfg, instant is $instant}
""")
        instant = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
        assert model.run(
            givens={"cfg": {"label": "ok", "n": 9007199254740993}, "instant": instant}
        ).to_dicts() == [
            {"cfg": {"label": "ok", "n": 9007199254740993}, "instant": instant}
        ]


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit])
def test_interrupt_during_schema_discovery_closes_the_session(monkeypatch, interrupt):
    execute = duckdb.DuckDBPyConnection.execute

    def interrupted(self, query, *args, **kwargs):
        if query.startswith("DESCRIBE"):
            raise interrupt()
        return execute(self, query, *args, **kwargs)

    monkeypatch.setattr(duckdb.DuckDBPyConnection, "execute", interrupted)
    with duckdb.connect() as connection:
        session = Session(connection=connection)
        with pytest.raises(interrupt):
            session.run(ONE)
        assert session.closed
        assert connection.execute("SELECT 42").fetchone() == (42,)


def test_inline_imports_do_not_shadow_physical_files(tmp_path):
    (tmp_path / "inline.malloy").write_text(
        "source: numbers is duckdb.sql('SELECT 42 AS value')"
    )
    with Session() as session:
        model = session.model(
            'import "inline.malloy"\nrun: numbers -> { select: value }',
            base_dir=tmp_path,
        )
        assert model.run().item() == 42
    (tmp_path / "inline.malloy").unlink()
    with Session() as session:
        with pytest.raises(CompilationError, match="inline.malloy"):
            session.model('import "inline.malloy"', base_dir=tmp_path)
        assert session.run(ONE).item() == 1


def test_model_reload_observes_new_schema_and_imports(tmp_path):
    data = tmp_path / "data.csv"
    data.write_text("value\n1\n")
    imported = tmp_path / "source.malloy"
    imported.write_text("source: numbers is duckdb.table('data.csv')")
    path = tmp_path / "main.malloy"
    path.write_text('import "source.malloy"\nrun: numbers -> { select: * }')
    with Session() as session:
        first = session.load(path)
        assert first.run().columns == ["value"]
        data.write_text("value,other\n2,42\n")
        assert first.run().to_dicts() == [{"value": 2}]
        with session.load(path) as fresh:
            assert fresh.run().to_dicts() == [{"value": 2, "other": 42}]
        imported.write_text("source: numbers is duckdb.sql('SELECT 99 AS replacement')")
        assert session.load(path).run().to_dicts() == [{"replacement": 99}]


def test_borrowed_connection_preserves_state_and_transactions():
    with duckdb.connect() as connection:
        connection.execute("SET TimeZone='Asia/Tokyo'")
        connection.execute("SET VARIABLE data_root = 'caller value'")
        connection.execute("CREATE TEMP TABLE values_table AS SELECT 1 AS n")
        connection.begin()
        connection.execute("INSERT INTO values_table VALUES (2)")
        with Session(connection=connection) as session:
            assert (
                session.run(
                    "run: duckdb.table('values_table') -> { aggregate: n is n.sum() }"
                ).item()
                == 3
            )
        assert connection.execute(
            "SELECT current_setting('TimeZone'), getvariable('data_root')"
        ).fetchone() == ("Asia/Tokyo", "caller value")
        connection.rollback()
        assert connection.execute("SELECT SUM(n) FROM values_table").fetchone() == (1,)


@pytest.mark.parametrize("borrowed", [False, True])
def test_session_connection_identity_is_fixed(borrowed):
    with duckdb.connect() as original, duckdb.connect() as replacement:
        session = Session(connection=original if borrowed else None)
        connection = session.connection
        with session:
            with pytest.raises(AttributeError):
                session.connection = replacement
            assert session.connection is connection
            assert session.run(ONE).item() == 1
        assert replacement.execute("SELECT 42").fetchone() == (42,)
        if borrowed:
            assert connection.execute("SELECT 42").fetchone() == (42,)
        else:
            with pytest.raises(duckdb.ConnectionException):
                connection.execute("SELECT 42")


def test_compile_and_execution_errors_leave_session_reusable():
    with Session() as session:
        with pytest.raises(CompilationError):
            session.run("run: undefined_source -> { select: missing }")
        session.connection.execute("CREATE TABLE bad_values AS SELECT 'bad' AS text")
        with pytest.raises(duckdb.ConversionException):
            session.run(
                "run: duckdb.table('bad_values') -> { select: parsed_number is text::number }"
            )
        assert session.run(ONE).item() == 1


def test_closed_model_does_not_close_its_session():
    with Session() as session:
        model = session.model(ONE)
        model.close()
        model.close()
        with pytest.raises(SessionError, match="Model is closed"):
            model.run()
        assert not session.closed
        assert session.run(ONE).item() == 1


def test_connection_inventory_refreshes_for_new_registered_names():
    with Session() as session:
        assert session.run(ONE).item() == 1
        session.connection.register("values.csv", pl.DataFrame({"n": [40, 2]}))
        assert (
            session.run(
                "run: duckdb.table('\"values.csv\"') -> { aggregate: total is n.sum() }"
            ).item()
            == 42
        )


def test_sessions_isolate_data_roots(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "data.csv").write_text("value\n10\n")
    (right / "data.csv").write_text("value\n20\n")
    source = "run: duckdb.table('data.csv') -> { select: value }"
    with Session(data_root=left) as a, Session(data_root=right) as b:
        am, bm = a.model(source), b.model(source)
        assert [am.run().item(), bm.run().item(), am.run().item()] == [10, 20, 10]


def test_concurrent_queries_use_one_persistent_process(monkeypatch):
    from pymalloy.server import _bridge

    original = _bridge.subprocess.Popen
    processes = []

    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(_bridge.subprocess, "Popen", spawn)
    with Session() as session:
        model = session.model("""
##! experimental.givens
given: value :: number is 0
source: one is duckdb.sql('SELECT 1 AS x')
run: one -> { select: value is $value }
""")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(lambda n: model.run(givens={"value": n}).item(), range(8))
            )
        assert results == list(range(8))
        assert len(processes) == 1
    assert processes[0].poll() == 0


def test_query_timeout_closes_session_but_keeps_borrowed_connection(monkeypatch):
    with duckdb.connect() as connection:
        started = threading.Event()
        sql = duckdb.DuckDBPyConnection.sql

        def execute(self, *args, **kwargs):
            started.set()
            return sql(self, *args, **kwargs)

        monkeypatch.setattr(duckdb.DuckDBPyConnection, "sql", execute)
        session = Session(connection=connection)
        model = session.model("""
source: numbers is duckdb.sql('SELECT i FROM range(100000000000) t(i)')
run: numbers -> { aggregate: total is i.sum() }
""")
        with pytest.raises(TimeoutError, match="session closed"):
            model.run(timeout=0.5)
        assert started.is_set()
        assert session.closed
        with pytest.raises(SessionError):
            model.run()
        assert connection.execute("SELECT 42").fetchone() == (42,)


def test_deno_exit_invalidates_models_and_releases_owned_resources(monkeypatch):
    from pymalloy.server import _bridge

    original = _bridge.subprocess.Popen
    processes = []

    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(_bridge.subprocess, "Popen", spawn)
    session = Session()
    model = session.model(ONE)
    processes[0].kill()
    processes[0].wait()
    with pytest.raises(SessionError, match="bridge"):
        model.run()
    assert session.closed
    with pytest.raises(SessionError, match="closed"):
        session.run(ONE)
    with pytest.raises(duckdb.ConnectionException):
        session.connection.execute("SELECT 1")


def test_owned_resources_close_on_exception():
    with pytest.raises(RuntimeError, match="caller failure"), Session() as session:
        connection = session.connection
        assert session.run(ONE).item() == 1
        raise RuntimeError("caller failure")
    assert session.closed
    session.close()
    with pytest.raises(duckdb.ConnectionException):
        connection.execute("SELECT 1")


def test_model_rejects_ambiguous_query_selection():
    with Session() as session:
        model = session.model(ONE)
        with pytest.raises(ValueError, match="source or query"):
            model.run(ONE, query="run:1")
        with pytest.raises(CompilationError, match="Unknown query"):
            model.run(query="missing")
        assert model.run().item() == 1


def test_waiting_query_timeout_preserves_the_active_session(monkeypatch):
    started, release = threading.Event(), threading.Event()
    sql = duckdb.DuckDBPyConnection.sql

    def execute(self, *args, **kwargs):
        started.set()
        if not release.wait(timeout=5):
            raise AssertionError("Active query was not released")
        return sql(self, *args, **kwargs)

    monkeypatch.setattr(duckdb.DuckDBPyConnection, "sql", execute)
    with Session() as session, ThreadPoolExecutor(max_workers=1) as pool:
        model = session.model(ONE)
        active = pool.submit(model.run)
        try:
            assert started.wait(timeout=5)
            with pytest.raises(TimeoutError, match="Waiting for the session"):
                model.run(timeout=0.05)
            assert not session.closed
        finally:
            release.set()
        assert active.result(timeout=5).item() == 1
        assert model.run().item() == 1


def test_unsearched_schema_table_does_not_mask_relative_data_file(tmp_path):
    (tmp_path / "orders.csv").write_text("amount\n42\n")
    with Session(data_root=tmp_path) as session:
        session.connection.execute(
            'CREATE SCHEMA secondary; CREATE TABLE secondary."orders.csv" AS SELECT 99 AS amount'
        )
        assert (
            session.run("run: duckdb.table('orders.csv') -> { select: amount }").item()
            == 42
        )


def test_search_path_resolves_case_insensitive_filename_tables_in_borrowed_transaction(
    tmp_path,
):
    with duckdb.connect() as connection:
        connection.execute(
            'CREATE SCHEMA secondary; CREATE TABLE secondary."ORDERS.CSV" AS SELECT 42 AS amount'
        )
        connection.execute("SET search_path='main,secondary'")
        connection.execute("BEGIN")
        with Session(connection=connection, data_root=tmp_path) as session:
            assert (
                session.run(
                    """run: duckdb.table('"orders.csv"') -> { select: amount }"""
                ).item()
                == 42
            )
        connection.execute('INSERT INTO secondary."ORDERS.CSV" VALUES (10)')
        connection.execute("ROLLBACK")
        assert connection.execute(
            'SELECT amount FROM secondary."ORDERS.CSV"'
        ).fetchall() == [(42,)]


def test_query_table_uses_quoted_database_identifiers_and_search_path(tmp_path):
    with Session(data_root=tmp_path) as session:
        session.connection.execute(
            'CREATE SCHEMA secondary; CREATE TABLE secondary."ORDERS.CSV" AS SELECT 42 AS amount'
        )
        session.connection.execute("SET search_path='main,secondary'")
        assert (
            session.run('''
run: duckdb.sql("""SELECT * FROM query_table('"orders.csv"')""") -> { select: amount }
''').item()
            == 42
        )


def test_missing_table_resolution_keeps_borrowed_transaction_available(tmp_path):
    (tmp_path / "orders.csv").write_text("amount\n42\n")
    with duckdb.connect() as connection:
        connection.execute("BEGIN")
        with Session(connection=connection, data_root=tmp_path) as session:
            assert (
                session.run(
                    "run: duckdb.table('orders.csv') -> { select: amount }"
                ).item()
                == 42
            )
        assert connection.execute("SELECT 1").fetchall() == [(1,)]
        connection.execute("ROLLBACK")


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ('WITH "Orders.CSV" AS (SELECT 1 AS value) SELECT * FROM "orders.csv"', [1]),
        (
            """SELECT * FROM "orders.csv"
UNION ALL
SELECT * FROM (WITH "orders.csv" AS (SELECT 1 AS value) SELECT * FROM "orders.csv")""",
            [1, 42],
        ),
        (
            '''WITH RECURSIVE "Numbers.CSV"(value) AS (
  SELECT 1 UNION ALL SELECT value + 1 FROM "numbers.csv" WHERE value < 3
) SELECT * FROM "numbers.csv"''',
            [1, 2, 3],
        ),
        ('WITH "Ä.csv" AS (SELECT 1 AS value) SELECT * FROM "ä.csv"', [42]),
        (
            '''WITH "orders.csv" AS (SELECT * FROM 'orders.csv') SELECT * FROM "orders.csv"''',
            [42],
        ),
        (
            '''WITH "z.csv" AS (SELECT 3 AS value), "a.csv" AS (SELECT * FROM "z.csv") SELECT * FROM "a.csv"''',
            [3],
        ),
        (
            """WITH first AS (SELECT * FROM 'orders.csv'), "orders.csv" AS (SELECT 1 AS value) SELECT * FROM first""",
            [42],
        ),
        (
            '''WITH RECURSIVE "orders.csv" AS (SELECT * FROM 'orders.csv' UNION ALL SELECT value + 1 FROM "orders.csv" WHERE value < 44) SELECT * FROM "orders.csv"''',
            [42, 43, 44],
        ),
        (
            """WITH "orders.csv" AS (SELECT 3 AS value) SELECT * FROM (WITH "orders.csv" AS (SELECT * FROM "orders.csv") SELECT * FROM "orders.csv")""",
            [3],
        ),
        (
            """WITH "orders.csv" AS (SELECT 1 AS value) SELECT * FROM query_table('orders.csv')""",
            [42],
        ),
        (
            """WITH "orders.csv" AS (SELECT 3 AS value) SELECT * FROM (WITH RECURSIVE "orders.csv" AS (SELECT * FROM "orders.csv" UNION ALL SELECT value + 1 FROM "orders.csv" WHERE value < 5) SELECT * FROM "orders.csv")""",
            [3, 4, 5],
        ),
    ],
)
def test_file_binding_preserves_duckdb_cte_scope_and_identifier_case(
    tmp_path, monkeypatch, sql, expected
):
    (tmp_path / "orders.csv").write_text("value\n42\n")
    (tmp_path / "ä.csv").write_text("value\n42\n")
    monkeypatch.chdir(tmp_path.parent)
    source = f'''source: numbers is duckdb.sql("""\n{sql}\n""")
run: numbers -> {{ select: value order_by: value }}'''
    with Session(data_root=tmp_path) as session:
        assert session.run(source)["value"].to_list() == expected
