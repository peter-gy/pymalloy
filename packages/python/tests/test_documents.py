import subprocess
import sys

import duckdb
import pytest
from test_compile import EXAMPLES, run_notebook
from test_jupyter import execute_notebook

from pymalloy.exports import Markdown, compile_document, jupyter, marimo


def test_document_records_import_with_base_dependencies():
    program = """
import importlib.abc
import sys
from pathlib import Path

class NativeImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'deno', 'duckdb', 'polars', 'pyarrow', 'sqlglot', 'marimo'}:
            raise AssertionError(f'Native dependency imported: {fullname}')

sys.meta_path.insert(0, NativeImports())
from pymalloy.exports import Document, Markdown, Query, compile_document, jupyter, marimo
query = Query('answer', 'SELECT 42 AS answer', 'select')
document = Document('Answer', (Markdown('# Answer'), query), Path.cwd())
assert document.queries == (query,)
assert 'SELECT 42 AS answer' in jupyter.render(document, output_path='answer.ipynb')
"""
    subprocess.run([sys.executable, "-c", program], check=True, timeout=20)


def test_notebook_preserves_markdown_and_embedded_sql(tmp_path):
    model = tmp_path / "sales.malloynb"
    model.write_text(f'''>>>markdown
# Regional sales
>>>malloy
import {{orders}} from "{(EXAMPLES / "orders.malloy").as_posix()}"
run: orders -> by_region
>>>markdown
## Total revenue
>>>sql connection:duckdb
SELECT SUM(revenue) AS total FROM (%{{ orders -> by_region }}%)
''')
    book = compile_document(model, data_root=EXAMPLES)
    assert [query.name for query in book.queries] == ["run:1", "sql:1"]
    assert [cell.text for cell in book.cells if isinstance(cell, Markdown)] == [
        "# Regional sales",
        "## Total revenue",
    ]
    output = tmp_path / "sales.py"
    output.write_text(marimo.render(book, output_path=output))
    definitions = run_notebook(output)
    assert definitions["run_1"].to_dicts() == [
        {"region": "North", "revenue": 105, "order_count": 3},
        {"region": "South", "revenue": 95, "order_count": 3},
    ]
    assert definitions["sql_1"].to_dicts() == [{"total": 200}]


def test_documentation_notebook_keeps_fenced_examples_as_markdown(tmp_path):
    model = tmp_path / "guide.malloynb"
    model.write_text(""">>>markdown
# Guide

```text
  >>>malloy
  source: example is unknown.table('example')
```
""")
    book = compile_document(model)
    assert book.queries == ()
    assert "unknown.table" in book.cells[0].text
    output = tmp_path / "guide.py"
    output.write_text(marimo.render(book, output_path=output))
    run_notebook(output)


def test_source_only_model_produces_a_source_inventory(tmp_path):
    model = tmp_path / "sources.malloy"
    model.write_text("source: numbers is duckdb.sql('SELECT 1 AS value')")
    book = compile_document(model)
    assert book.queries == ()
    assert "`numbers`" in book.cells[0].text


def test_all_queries_includes_runs_named_queries_and_source_views(tmp_path):
    model = tmp_path / "sales.malloy"
    model.write_text(f'''
import {{orders}} from "{(EXAMPLES / "orders.malloy").as_posix()}"
source: sales is orders
query: summary is sales -> by_region
run: summary
''')
    book = compile_document(model, data_root=EXAMPLES, queries=["*"])
    assert [query.name for query in book.queries] == [
        "run:1",
        "summary",
        "sales.by_region",
        "sales.monthly_revenue",
        "sales.region_detail",
    ]


def test_lateral_unnest_preserves_named_ordinality(tmp_path):
    model = tmp_path / "ordinality.malloy"
    model.write_text('''
source: entries is duckdb.sql("""
  SELECT u.row_id, u.value
  FROM (SELECT [10, 20] AS values) AS input
  LEFT JOIN LATERAL UNNEST(input.values) WITH ORDINALITY AS u(value, row_id) ON TRUE
""")
run: entries -> { select: row_id, value order_by: row_id }
''')
    book = compile_document(model)
    output = tmp_path / "ordinality.py"
    output.write_text(marimo.render(book, output_path=output))
    assert run_notebook(output)["run_1"].to_dicts() == [
        {"row_id": 1, "value": 10},
        {"row_id": 2, "value": 20},
    ]


def test_copy_executes_in_notebook_against_the_data_root(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    model = tmp_path / "build.malloynb"
    model.write_text(""">>>markdown
# Export
>>>sql connection:duckdb
COPY (SELECT 42 AS value) TO 'output.parquet' (FORMAT PARQUET)
>>>markdown
## Read the export
>>>sql
SELECT * FROM 'output.parquet'
""")
    book = compile_document(model, data_root=root)
    assert not (root / "output.parquet").exists()
    output = tmp_path / "build.py"
    output.write_text(marimo.render(book, output_path=output))
    definitions = run_notebook(output)
    assert definitions["sql_1"].is_empty()
    assert definitions["sql_2"].to_dicts() == [{"value": 42}]
    with duckdb.connect() as connection:
        assert connection.execute(
            "SELECT * FROM read_parquet(?)", [str(root / "output.parquet")]
        ).fetchall() == [(42,)]


@pytest.mark.parametrize("renderer,suffix", [(marimo, ".py"), (jupyter, ".ipynb")])
def test_given_values_bind_runs_and_embedded_queries_for_each_export(
    tmp_path, renderer, suffix
):
    model = tmp_path / "filtered.malloynb"
    model.write_text(""">>>markdown
# Filtered numbers
>>>malloy
##! experimental.givens
given: minimum :: number
source: numbers is duckdb.sql('SELECT unnest([2, 12, 42]) AS value')
run: numbers -> { where: value >= $minimum select: value order_by: value }
>>>sql connection:duckdb
SELECT SUM(value) AS total FROM (%{ numbers -> {
  where: value >= $minimum select: value
} }%)
""")
    document = compile_document(model, givens={"minimum": 20})
    assert [query.kind for query in document.queries] == ["select", "select"]
    selected = compile_document(
        model, queries=["sql:1", "run:1"], givens={"minimum": 20}
    )
    assert selected.queries == tuple(reversed(document.queries))
    assert compile_document(model, givens={"minimum": 10}) != document
    assert compile_document(model, givens={"minimum": 20}) == document
    output = tmp_path / ("filtered" + suffix)
    output.write_text(renderer.render(document, output_path=output))
    if renderer is marimo:
        definitions = run_notebook(output)
        assert definitions["run_1"].to_dicts() == [{"value": 42}]
        assert definitions["sql_1"].to_dicts() == [{"total": 42}]
    else:
        execute_notebook(
            output,
            "assert run_1.to_dicts() == [{'value': 42}]\n"
            "assert sql_1.to_dicts() == [{'total': 42}]",
        )
