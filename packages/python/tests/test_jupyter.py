import json
import subprocess
from pathlib import Path

import duckdb
import nbformat
from nbclient import NotebookClient
from test_compile import EXAMPLES

from pymalloy.export import Document, Markdown, Query, compile, jupyter


def execute_notebook(output: Path, assertions: str = "", *, pymalloy: bool = False):
    notebook = nbformat.read(output, as_version=4)
    nbformat.validate(notebook)
    # The kernel models an export environment with DuckDB and Polars installed.
    if not pymalloy:
        notebook.cells.insert(
            0,
            nbformat.v4.new_code_cell(
                "import sys\nsys.modules.update(pymalloy=None, deno=None, pyarrow=None)"
            ),
        )
    if assertions:
        notebook.cells.append(nbformat.v4.new_code_cell(assertions))
    return NotebookClient(
        notebook,
        timeout=30,
        kernel_name="python3",
        resources={"metadata": {"path": str(output.parent)}},
    ).execute()


def test_jupyter_executes_exported_views_with_exact_nested_results(tmp_path):
    document = compile(EXAMPLES / "orders.malloy")
    output = tmp_path / "orders.ipynb"
    output.write_text(jupyter.render(document, output_path=output))
    executed = execute_notebook(
        output,
        """
assert orders_by_region.to_dicts() == [
    {"region": "North", "revenue": 105, "order_count": 3},
    {"region": "South", "revenue": 95, "order_count": 3},
]
assert orders_region_detail.to_dicts() == [
    {"region": "North", "revenue": 105, "categories": [
        {"category": "Books", "revenue": 55}, {"category": "Games", "revenue": 50}
    ]},
    {"region": "South", "revenue": 95, "categories": [
        {"category": "Books", "revenue": 55}, {"category": "Games", "revenue": 40}
    ]},
]
assert str(orders_monthly_revenue["order_month"][0]) == "2026-01-01 00:00:00"
assert orders_monthly_revenue["revenue"].to_list() == [100, 100]
""",
    )
    results = [
        item
        for cell in executed.cells
        if cell.cell_type == "code"
        for item in cell.outputs
        if item.output_type == "execute_result"
    ]
    assert len(results) == 3
    assert "North" in results[0].data["text/plain"]


def test_jupyter_serialization_is_deterministic_and_preserves_authored_markdown(
    tmp_path,
):
    title = '# Sales """ \\ £ {amount}'
    document = Document(
        title="Sales",
        cells=(
            Markdown(title),
            Query("report", "SELECT '{literal}' AS value", "select"),
        ),
        data_root=tmp_path,
    )
    output = tmp_path / "report.ipynb"
    first = jupyter.render(document, output_path=output)
    assert first == jupyter.render(document, output_path=output)
    content = nbformat.reads(first, as_version=4)
    nbformat.validate(content)
    assert content.cells[0].source == title
    output.write_text(first)
    execute_notebook(
        output,
        "assert report.to_dicts() == [{'value': '{literal}'}]",
    )


def test_jupyter_copy_executes_before_following_query(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    model = tmp_path / "copy.malloynb"
    model.write_text(""">>>markdown
# Saved rows
>>>sql connection:duckdb
COPY (SELECT 42 AS value) TO 'answer.parquet' (FORMAT PARQUET)
>>>markdown
## Read saved rows
>>>sql
SELECT * FROM 'answer.parquet'
""")
    document = compile(model, data_root=data)
    assert not (data / "answer.parquet").exists()
    output = tmp_path / "copy.ipynb"
    output.write_text(jupyter.render(document, output_path=output))
    execute_notebook(
        output,
        "assert sql_0.is_empty()\nassert sql_1.to_dicts() == [{'value': 42}]",
    )
    with duckdb.connect() as connection:
        assert connection.execute(
            "SELECT * FROM read_parquet(?)", [str(data / "answer.parquet")]
        ).fetchall() == [(42,)]


def test_jupyter_preserves_readonly_database_access(tmp_path):
    database = tmp_path / "data.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE TABLE numbers AS SELECT 42 AS value")
    model = tmp_path / "numbers.malloy"
    model.write_text("run: duckdb.table('numbers') -> { select: value }")
    document = compile(model, database=database)
    output = tmp_path / "numbers.ipynb"
    output.write_text(jupyter.render(document, output_path=output))
    execute_notebook(
        output,
        """
assert run_0.to_dicts() == [{"value": 42}]
with connect() as connection:
    try:
        connection.execute("DELETE FROM numbers")
    except duckdb.InvalidInputException:
        pass
    else:
        raise AssertionError("Expected the database connection to be read-only")
with duckdb.connect(str(database)) as writable:
    assert writable.execute("SELECT * FROM numbers").fetchone() == (42,)
""",
    )


def test_cli_exports_jupyter_notebook(tmp_path):
    output = tmp_path / "orders.ipynb"
    result = subprocess.run(
        [
            "pymalloy",
            "export",
            str(EXAMPLES / "orders.malloy"),
            "--format",
            "jupyter",
            "--query",
            "orders.by_region",
            "--title",
            "Regional sales",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    document = json.loads(output.read_text())
    assert document["metadata"]["title"] == "Regional sales"
    execute_notebook(
        output,
        "assert orders_by_region['revenue'].to_list() == [105, 95]",
    )
