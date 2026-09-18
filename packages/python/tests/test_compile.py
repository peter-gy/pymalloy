import importlib.util
import subprocess
from pathlib import Path

import duckdb
import pytest

from pymalloy.exports import compile_document, marimo
from pymalloy.server import CompilationError

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


def run_notebook(path):
    spec = importlib.util.spec_from_file_location("compiled_notebook", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _, definitions = module.app.run()
    return definitions


def test_source_views_render_and_execute_from_another_directory(tmp_path, monkeypatch):
    book = compile_document(EXAMPLES / "orders.malloy")
    assert [query.name for query in book.queries] == [
        "orders.by_region",
        "orders.monthly_revenue",
        "orders.region_detail",
    ]
    output = tmp_path / "report.py"
    output.write_text(marimo.render(book, output_path=output))
    monkeypatch.chdir(tmp_path)
    definitions = run_notebook(output)
    assert definitions["orders_by_region"].to_dicts() == [
        {"region": "North", "revenue": 105, "order_count": 3},
        {"region": "South", "revenue": 95, "order_count": 3},
    ]
    assert definitions["orders_region_detail"].to_dicts() == [
        {
            "region": "North",
            "revenue": 105,
            "categories": [
                {"category": "Books", "revenue": 55},
                {"category": "Games", "revenue": 50},
            ],
        },
        {
            "region": "South",
            "revenue": 95,
            "categories": [
                {"category": "Books", "revenue": 55},
                {"category": "Games", "revenue": 40},
            ],
        },
    ]


def test_compilation_is_byte_deterministic(tmp_path):
    output = tmp_path / "report.py"
    first = compile_document(EXAMPLES / "orders.malloy")
    second = compile_document(EXAMPLES / "orders.malloy")
    assert marimo.render(first, output_path=output) == marimo.render(
        second, output_path=output
    )


def test_imports_named_queries_and_ordered_runs(tmp_path):
    (tmp_path / "model.malloy").write_text(
        f'import {{orders}} from "{(EXAMPLES / "orders.malloy").as_posix()}"\n'
        "query: summary is orders -> by_region\n"
        "run: orders -> monthly_revenue\n"
        "run: summary\n"
    )
    book = compile_document(tmp_path / "model.malloy", data_root=EXAMPLES)
    assert [q.name for q in book.queries] == ["run:1", "run:2"]
    selected = compile_document(
        tmp_path / "model.malloy", data_root=EXAMPLES, queries=["summary", "run:1"]
    )
    assert [q.name for q in selected.queries] == ["summary", "run:1"]
    assert selected.queries[0].sql == book.queries[1].sql
    assert selected.queries[1].sql == book.queries[0].sql


def test_sql_source_with_nested_types(tmp_path):
    model = tmp_path / "nested.malloy"
    model.write_text('''
source: events is duckdb.sql("""
    SELECT 1 AS id, [{'label': 'a', 'value': 2}, {'label': 'b', 'value': 3}] AS items
""")
run: events -> { group_by: items.label aggregate: total is items.value.sum() order_by: 1 }
''')
    book = compile_document(model)
    with duckdb.connect() as connection:
        assert connection.execute(book.queries[0].sql).fetchall() == [
            ("a", 2),
            ("b", 3),
        ]


def test_persistent_database_and_join_aggregates(tmp_path):
    database = tmp_path / "sales.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "CREATE TABLE customers AS SELECT 1 AS id, 'Ada' AS name, 10 AS budget"
        )
        connection.execute(
            "CREATE TABLE orders AS SELECT 1 AS customer_id, unnest([2, 3]) AS amount"
        )
    model = tmp_path / "sales.malloy"
    model.write_text("""
source: customers is duckdb.table('customers') extend { primary_key: id }
source: orders is duckdb.table('orders') extend {
  join_one: customers on customer_id = customers.id
}
query: totals is orders -> {
  aggregate: revenue is amount.sum(), budget is customers.budget.sum()
}
""")
    book = compile_document(model, database=database)
    output = tmp_path / "report.py"
    output.write_text(marimo.render(book, output_path=output))
    definitions = run_notebook(output)
    assert definitions["totals"].to_dicts() == [{"revenue": 5, "budget": 10}]
    with (
        definitions["connect"]() as connection,
        pytest.raises(duckdb.InvalidInputException, match="read-only"),
    ):
        connection.execute("DELETE FROM orders")
    with duckdb.connect(str(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone() == (2,)


def test_literals_and_python_names_survive_notebook_rendering(tmp_path):
    model = tmp_path / "quotes.malloy"
    model.write_text("""
source: values is duckdb.sql("SELECT '{literal}' AS value")
query: `class` is values -> { select: value }
query: `a-b` is values -> { select: value }
query: a_b is values -> { select: value }
query: connection is values -> { select: value }
""")
    book = compile_document(model, title='A """ title with \\ and {braces}')
    output = tmp_path / "quotes.py"
    output.write_text(marimo.render(book, output_path=output))
    definitions = run_notebook(output)
    for name in ["result_class", "a_b", "a_b_2", "connection_2"]:
        assert definitions[name].to_dicts() == [{"value": "{literal}"}]


@pytest.mark.parametrize(
    "source, message",
    [
        ("source: bad is duckdb.table('missing.csv')", "missing.csv"),
        ("run: missing -> { select: field }", "missing"),
        ("source: bad is bigquery.table('project.table')", "bigquery"),
    ],
)
def test_compilation_errors_report_the_input(tmp_path, source, message):
    model = tmp_path / "invalid.malloy"
    model.write_text(source)
    with pytest.raises(CompilationError, match=message):
        compile_document(model)


def test_unknown_query_lists_available_choices():
    with pytest.raises(CompilationError, match="orders.by_region"):
        compile_document(EXAMPLES / "orders.malloy", queries=["missing"])


def test_cli_failure_preserves_existing_output(tmp_path):
    output = tmp_path / "report.py"
    output.write_text("existing notebook\n")
    result = subprocess.run(
        [
            "pymalloy",
            "export",
            "--format",
            "marimo",
            str(EXAMPLES / "orders.malloy"),
            "--query",
            "missing",
            "-o",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "Unknown query 'missing'" in result.stderr
    assert output.read_text() == "existing notebook\n"


def test_compilation_timeout_is_bounded():
    with pytest.raises(CompilationError, match="exceeded"):
        compile_document(EXAMPLES / "orders.malloy", timeout=0.001)


@pytest.mark.parametrize(
    "source",
    [
        "duckdb.table('orders.csv')",
        """duckdb.sql("SELECT orders.amount FROM 'orders.csv'")""",
        """duckdb.sql("SELECT * FROM read_csv(['orders.csv'])")""",
        """duckdb.sql("SELECT * FROM query_table(['orders.csv'])")""",
    ],
)
def test_data_root_wins_over_conflicting_working_directory(
    tmp_path, monkeypatch, source
):
    root = tmp_path / "data's directory"
    root.mkdir()
    (root / "orders.csv").write_text("amount\n42\n")
    (tmp_path / "orders.csv").write_text("wrong_column\n99\n")
    model = root / "model.malloy"
    model.write_text(f"source: orders is {source}\nrun: orders -> {{ select: amount }}")
    monkeypatch.chdir(tmp_path)
    book = compile_document(model)
    output = tmp_path / "report.py"
    output.write_text(marimo.render(book, output_path=output))
    assert run_notebook(output)["run_1"].to_dicts() == [{"amount": 42}]


def test_notebook_preserves_utc_timestamp_semantics(tmp_path):
    model = tmp_path / "time.malloy"
    model.write_text("""
source: times is duckdb.sql("SELECT CAST(TIMESTAMPTZ '2026-01-01 23:30:00+00' AS DATE) AS day_value")
run: times -> { select: day_value }
""")
    book = compile_document(model)
    output = tmp_path / "time.py"
    output.write_text(marimo.render(book, output_path=output))
    assert str(run_notebook(output)["run_1"].to_dicts()[0]["day_value"]) == "2026-01-01"


@pytest.mark.parametrize("table", ["main.csv", 'main."orders.csv"'])
def test_database_tables_with_file_like_names(tmp_path, table):
    database = tmp_path / "data.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(f"CREATE TABLE {table} AS SELECT 42 AS amount")
    model = tmp_path / "tables.malloy"
    model.write_text(f"run: duckdb.table('{table}') -> {{ select: amount }}")
    book = compile_document(model, database=database)
    output = tmp_path / "tables.py"
    output.write_text(marimo.render(book, output_path=output))
    definitions = run_notebook(output)
    assert definitions["run_1"].to_dicts() == [{"amount": 42}]


def test_generated_connections_close_after_success_and_failure(tmp_path):
    book = compile_document(EXAMPLES / "orders.malloy")
    output = tmp_path / "report.py"
    output.write_text(marimo.render(book, output_path=output))
    definitions = run_notebook(output)
    with definitions["connect"]() as first:
        assert first.execute("SELECT 1").fetchone() == (1,)
    with pytest.raises(duckdb.ConnectionException, match="closed"):
        first.execute("SELECT 1")
    with (
        pytest.raises(RuntimeError, match="query failed"),
        definitions["connect"]() as failed,
    ):
        raise RuntimeError("query failed")
    with pytest.raises(duckdb.ConnectionException, match="closed"):
        failed.execute("SELECT 1")


def test_cli_export_binds_required_given_values(tmp_path):
    model = tmp_path / "filtered.malloy"
    model.write_text("""
##! experimental.givens
given: minimum :: number
source: numbers is duckdb.sql('SELECT unnest([2, 12, 42]) AS value')
run: numbers -> { where: value >= $minimum select: value }
""")
    output = tmp_path / "filtered.py"
    result = subprocess.run(
        [
            "pymalloy",
            "export",
            str(model),
            "--format",
            "marimo",
            "--givens",
            '{"minimum": 20}',
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert run_notebook(output)["run_1"].to_dicts() == [{"value": 42}]


@pytest.mark.parametrize(
    "values", ["[]", "{broken", '{"minimum": NaN}', '{"minimum": 1e999}']
)
def test_cli_rejects_invalid_givens_before_replacing_output(tmp_path, values):
    output = tmp_path / "report.py"
    output.write_text("existing notebook\n")
    result = subprocess.run(
        [
            "pymalloy",
            "export",
            str(EXAMPLES / "orders.malloy"),
            "--format",
            "marimo",
            "--givens",
            values,
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "givens" in result.stderr.lower()
    assert output.read_text() == "existing notebook\n"
