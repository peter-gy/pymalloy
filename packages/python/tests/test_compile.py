import importlib.util
import subprocess
from pathlib import Path

import duckdb
import pytest

from pymalloy import CompilationError, CompilerError, ExecutionError, SchemaError
from pymalloy.export import marimo, prepare

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


def run_notebook(path):
    spec = importlib.util.spec_from_file_location("compiled_notebook", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _, definitions = module.app.run()
    return definitions


def test_source_view_export_is_reproducible_and_runs_from_another_directory(
    tmp_path, monkeypatch
):
    book = prepare(EXAMPLES / "orders.malloy")
    assert [query.name for query in book.queries] == [
        "orders.by_region",
        "orders.monthly_revenue",
        "orders.region_detail",
    ]
    output = tmp_path / "report.py"
    source = marimo.render(book, output_path=output)
    assert source == marimo.render(
        prepare(EXAMPLES / "orders.malloy"), output_path=output
    )
    output.write_text(source)
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


def test_imports_named_queries_and_ordered_runs(tmp_path):
    (tmp_path / "model.malloy").write_text(
        f'import {{orders}} from "{(EXAMPLES / "orders.malloy").as_posix()}"\n'
        "query: summary is orders -> by_region\n"
        "run: orders -> monthly_revenue\n"
        "run: summary\n"
    )
    book = prepare(tmp_path / "model.malloy", data_root=EXAMPLES)
    assert [q.name for q in book.queries] == ["run:0", "run:1"]
    selected = prepare(
        tmp_path / "model.malloy", data_root=EXAMPLES, queries=["summary", "run:0"]
    )
    assert [q.name for q in selected.queries] == ["summary", "run:0"]
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
    book = prepare(model)
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
    book = prepare(model, database=database)
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
    book = prepare(model, title='A """ title with \\ and {braces}')
    output = tmp_path / "quotes.py"
    output.write_text(marimo.render(book, output_path=output))
    definitions = run_notebook(output)
    for name in ["result_class", "a_b", "a_b_2", "connection"]:
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
        prepare(model)


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
    assert "orders.by_region" in result.stderr
    assert output.read_text() == "existing notebook\n"


def test_export_timeout_covers_preparation_and_closes_the_model(monkeypatch):
    import time
    from types import SimpleNamespace

    import pymalloy as pm
    from pymalloy.export import _compile

    started = time.monotonic()
    elapsed = started
    opened = []
    create = pm.model

    def load(*args, **kwargs):
        nonlocal elapsed
        model = create(*args, **kwargs)
        opened.append(model)
        elapsed = started + 121
        return model

    monkeypatch.setattr(_compile, "time", SimpleNamespace(monotonic=lambda: elapsed))
    monkeypatch.setattr(pm, "model", load)
    with pytest.raises(TimeoutError, match="exceeded"):
        prepare(EXAMPLES / "orders.malloy", timeout=120)
    assert opened and all(model.closed for model in opened)


@pytest.mark.parametrize(
    "source",
    [
        "duckdb.table('orders.csv')",
        """duckdb.sql("SELECT orders.amount FROM 'orders.csv'")""",
        """duckdb.sql("SELECT * FROM read_csv(['orders.csv'])")""",
        """duckdb.sql("SELECT * FROM query_table(['orders.csv'])")""",
    ],
)
def test_export_rejects_current_directory_shadowing_before_compile_and_replay(
    tmp_path, monkeypatch, source
):
    root = tmp_path / "data's directory"
    root.mkdir()
    (root / "orders.csv").write_text("amount\n42\n")
    (tmp_path / "orders.csv").write_text("amount\n99\n")
    model = root / "model.malloy"
    model.write_text(f"source: orders is {source}\nrun: orders -> {{ select: amount }}")
    monkeypatch.chdir(tmp_path)
    files = {"orders.csv": root / "orders.csv"}
    with pytest.raises(ValueError, match="shadowed by the current directory"):
        prepare(model, files=files)
    (tmp_path / "orders.csv").unlink()
    book = prepare(model, files=files)
    output = tmp_path / "report.py"
    output.write_text(marimo.render(book, output_path=output))
    assert run_notebook(output)["run_0"].to_dicts() == [{"amount": 42}]
    (tmp_path / "orders.csv").write_text("amount\n99\n")
    with pytest.raises(ValueError, match="shadowed by the current directory"):
        run_notebook(output)


def test_notebook_preserves_utc_timestamp_semantics(tmp_path):
    model = tmp_path / "time.malloy"
    model.write_text("""
source: times is duckdb.sql("SELECT CAST(TIMESTAMPTZ '2026-01-01 23:30:00+00' AS DATE) AS day_value")
run: times -> { select: day_value }
""")
    book = prepare(model)
    output = tmp_path / "time.py"
    output.write_text(marimo.render(book, output_path=output))
    assert str(run_notebook(output)["run_0"].to_dicts()[0]["day_value"]) == "2026-01-01"


@pytest.mark.parametrize("table", ["main.csv", 'main."orders.csv"'])
def test_database_tables_with_file_like_names(tmp_path, table):
    database = tmp_path / "data.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(f"CREATE TABLE {table} AS SELECT 42 AS amount")
    model = tmp_path / "tables.malloy"
    model.write_text(f"run: duckdb.table('{table}') -> {{ select: amount }}")
    book = prepare(model, database=database)
    output = tmp_path / "tables.py"
    output.write_text(marimo.render(book, output_path=output))
    definitions = run_notebook(output)
    assert definitions["run_0"].to_dicts() == [{"amount": 42}]


def test_generated_connections_close_after_success_and_failure(tmp_path):
    book = prepare(EXAMPLES / "orders.malloy")
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
    assert run_notebook(output)["run_0"].to_dicts() == [{"value": 42}]


@pytest.mark.parametrize(
    "arguments,message",
    [
        pytest.param(["--givens", "[]"], "givens", id="givens-object"),
        pytest.param(["--givens", "{broken"], "givens", id="givens-json"),
        pytest.param(["--givens", '{"minimum": NaN}'], "givens", id="givens-constant"),
        pytest.param(
            ["--givens", '{"minimum": 1e999}'], "givens", id="givens-overflow"
        ),
        pytest.param(
            ["--files", '["orders.csv"]'],
            "files must be a JSON object",
            id="files-object",
        ),
        pytest.param(
            ["--files", '{"orders.csv": 42}'],
            "files must be a JSON object",
            id="files-path",
        ),
        pytest.param(
            ["--all", "--query", "run:0"],
            "not allowed with argument",
            id="selection-conflict",
        ),
    ],
)
def test_cli_rejects_invalid_export_options_before_replacing_output(
    tmp_path, arguments, message
):
    output = tmp_path / "report.ipynb"
    output.write_text("existing notebook\n")
    result = subprocess.run(
        [
            "pymalloy",
            "export",
            str(EXAMPLES / "orders.malloy"),
            "--format",
            "jupyter",
            "--output",
            str(output),
            *arguments,
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert message in result.stderr
    assert output.read_text() == "existing notebook\n"


def test_cli_version_and_run_bind_parameters(tmp_path):
    import importlib.metadata
    import json

    version = subprocess.run(
        ["pymalloy", "--version"], capture_output=True, text=True, check=True
    )
    assert (
        version.stdout.strip() == f"pymalloy {importlib.metadata.version('pymalloy')}"
    )
    path = tmp_path / "numbers.malloy"
    path.write_text(
        "##! experimental.givens\ngiven: minimum :: number\nrun: duckdb.sql('SELECT unnest([2, 42]) AS value') -> { where: value >= $minimum select: value }"
    )
    result = subprocess.run(
        ["pymalloy", "run", str(path), "--givens", '{"minimum": 20}'],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == [{"value": 42}]


def test_export_file_guard_preserves_catalog_table_precedence(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    (root / "orders.csv").write_text("amount\n42\n")
    (tmp_path / "orders.csv").write_text("amount\n99\n")
    database = root / "catalog.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE SCHEMA orders")
        connection.execute("CREATE TABLE orders.csv AS SELECT 7 AS amount")
    path = root / "model.malloy"
    path.write_text("run: duckdb.table('orders.csv') -> { select: amount }")
    monkeypatch.chdir(tmp_path)
    document = prepare(path, database=database)
    output = tmp_path / "report.py"
    output.write_text(marimo.render(document, output_path=output))
    assert run_notebook(output)["run_0"].to_dicts() == [{"amount": 7}]


@pytest.mark.parametrize("command", ["check", "export"])
@pytest.mark.parametrize(
    "failure",
    [
        CompilerError("compiler unavailable"),
        SchemaError("schema unavailable", sql="DESCRIBE x"),
        TimeoutError("deadline exceeded"),
        duckdb.IOException("input unavailable"),
    ],
    ids=["compiler", "schema", "deadline", "engine-io"],
)
def test_cli_reports_operational_failures_without_replacing_output(
    tmp_path, monkeypatch, capsys, command, failure
):
    import sys

    source = tmp_path / "model.malloy"
    source.write_text("run: missing")
    output = tmp_path / "report.ipynb"
    output.write_text("existing notebook")
    arguments = ["pymalloy", command, str(source)]
    if command == "export":
        arguments.extend(["--format", "jupyter", "--output", str(output)])
    import pymalloy as pm
    import pymalloy.export as exporter
    from pymalloy.cli import main

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(pm, "check", fail)
    monkeypatch.setattr(exporter, "prepare", fail)
    monkeypatch.setattr(sys, "argv", arguments)
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"pymalloy: {failure}\n"
    assert output.read_text() == "existing notebook"


@pytest.mark.parametrize("profile", ["precompiled", "headless"])
def test_native_exports_require_declared_sql_reader_inputs(
    tmp_path, monkeypatch, profile
):
    root = tmp_path / "data"
    root.mkdir()
    (root / "rows.csv").write_text("value\n42\n")
    (tmp_path / "rows.csv").write_text("value\n99\n")
    path = root / "model.malloy"
    path.write_text(
        "run: duckdb.sql(\"SELECT * FROM read_csv('rows.csv')\") -> {select:value}"
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(CompilationError, match="disabled") as failed:
        prepare(path, profile=profile)
    assert any("files=" in note for note in failed.value.__notes__)
    (tmp_path / "rows.csv").unlink()
    document = prepare(path, profile=profile, files={"rows.csv": root / "rows.csv"})
    output = tmp_path / "report.py"
    output.write_text(marimo.render(document, output_path=output))
    values = run_notebook(output)
    try:
        assert values["run_0"].to_dicts() == [{"value": 42}]
    finally:
        if profile == "headless":
            values["model"].close()


@pytest.mark.parametrize("profile", ["precompiled", "headless"])
def test_raw_sql_notebook_cannot_read_undeclared_files(tmp_path, monkeypatch, profile):
    root = tmp_path / "data"
    root.mkdir()
    (root / "rows.csv").write_text("value\n42\n")
    (tmp_path / "rows.csv").write_text("value\n99\n")
    path = root / "model.malloynb"
    path.write_text(">>>sql connection:duckdb\nSELECT * FROM read_csv('rows.csv')\n")
    document = prepare(path, profile=profile)
    output = tmp_path / "report.py"
    output.write_text(marimo.render(document, output_path=output))
    monkeypatch.chdir(tmp_path)
    expected = ExecutionError if profile == "headless" else duckdb.PermissionException
    with pytest.raises(expected, match="disabled"):
        run_notebook(output)


def test_generated_marimo_setup_is_an_ordinary_callable_python_cell(tmp_path):
    import ast
    import inspect
    from contextlib import contextmanager
    from types import SimpleNamespace

    from pymalloy.export import Document, QueryCell

    data = tmp_path / "data"
    data.mkdir()
    (data / "rows.csv").write_text("value\n42\n")
    document = Document(
        "Rows",
        (QueryCell("rows", "SELECT * FROM 'rows.csv'", "select"),),
        data_root=data,
        files={"rows.csv": data / "rows.csv"},
    )
    output = tmp_path / "report.py"
    tree = ast.parse(marimo.render(document, output_path=output))
    setup = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(statement, ast.FunctionDef) and statement.name == "connect"
            for statement in node.body
        )
    )
    setup.decorator_list = []
    setup.name = "setup"
    standalone = tmp_path / "setup_cell.py"
    standalone.write_text(ast.unparse(ast.Module(body=[setup], type_ignores=[])))
    spec = importlib.util.spec_from_file_location("setup_cell", standalone)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inputs = {
        "Path": Path,
        "contextmanager": contextmanager,
        "duckdb": duckdb,
        "mo": SimpleNamespace(notebook_dir=lambda: tmp_path),
    }
    returned = module.setup(
        **{name: inputs[name] for name in inspect.signature(module.setup).parameters}
    )
    names = [name.id for name in setup.body[-1].value.elts]
    definitions = dict(zip(names, returned, strict=True))
    with definitions["connect"]() as connection:
        assert connection.execute("SELECT * FROM 'rows.csv'").fetchall() == [(42,)]
