import pytest
from test_compile import run_notebook

from pymalloy.exports import compile_document, marimo
from pymalloy.server import CompilationError


def test_widget_export_preserves_files_for_full_model_and_sql_cells(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    for name, value in [("one", 1), ("two", 2), ("three", 3)]:
        (data / f"{name}.csv").write_text(f"value\n{value}\n")
    model = tmp_path / "model.malloynb"
    model.write_text(""">>>malloy
source: selected is duckdb.table('one.csv')
source: other is duckdb.sql("SELECT * FROM read_csv(['two.csv'])") extend {
  view: entries is { select: value }
}
run: selected -> { select: value }
>>>sql connection:duckdb
SELECT * FROM query_table(['three.csv'])
""")
    document = compile_document(
        model, data_root=data, profile="widget", queries=["run:1"]
    )
    assert [query.name for query in document.queries] == ["run:1"]
    output = tmp_path / "widget.py"
    output.write_text(marimo.render(document, output_path=output))
    model.unlink()
    values = run_notebook(output)
    widget = values["run_1"]
    try:
        assert {
            name: widget.files[name] for name in ("one.csv", "two.csv", "three.csv")
        } == {
            f"{name}.csv": (data / f"{name}.csv").read_bytes()
            for name in ("one", "two", "three")
        }
    finally:
        widget.close()


@pytest.mark.parametrize(
    "source,message",
    [
        (
            "run: duckdb.table('*.csv') -> { select: value }",
            "list the files explicitly",
        ),
        (
            "run: duckdb.table('numbers#one.csv') -> { select: value }",
            "rename the file",
        ),
        (
            "run: duckdb.table('s3://bucket/numbers.csv') -> { select: value }",
            "local path or HTTP",
        ),
        (
            (
                "run: duckdb.sql(\"SELECT * FROM query_table(getvariable('file'))\")"
                " -> { select: value }"
            ),
            "literal query_table paths",
        ),
        (
            (
                ">>>sql connection:duckdb\n"
                "COPY (SELECT 1 AS value) TO 'output.csv' (FORMAT CSV)"
            ),
            "cannot execute COPY",
        ),
    ],
)
def test_widget_export_rejects_unrepresentable_data_access(tmp_path, source, message):
    path = tmp_path / ("model.malloynb" if source.startswith(">>>") else "model.malloy")
    path.write_text(source)
    with pytest.raises(CompilationError, match=message):
        compile_document(path, profile="widget")


def test_widget_export_rejects_native_database(tmp_path):
    import duckdb

    database = tmp_path / "data.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE TABLE numbers AS SELECT 1 AS value")
    model = tmp_path / "model.malloy"
    model.write_text("run: duckdb.table('numbers') -> { select: value }")
    with pytest.raises(CompilationError, match="cannot use a native DuckDB database"):
        compile_document(model, profile="widget", database=database)
