import gc
import json
import subprocess

import duckdb
import pytest
from test_compile import run_notebook
from test_jupyter import execute_notebook

from pymalloy import ModelSource
from pymalloy.exports import compile_document, jupyter, marimo
from pymalloy.server import CompilationError, Session


@pytest.mark.parametrize("renderer,suffix", [(marimo, ".py"), (jupyter, ".ipynb")])
def test_hydrated_notebook_preserves_full_model_after_sources_are_removed(
    tmp_path, renderer, suffix
):
    data = tmp_path / "data"
    data.mkdir()
    (data / "numbers.csv").write_text("value\n2\n12\n42\n")
    authored = tmp_path / "authored"
    (authored / "models").mkdir(parents=True)
    (authored / "shared").mkdir()
    base = authored / "models" / "base.malloy"
    schema = authored / "shared" / "schema.malloy"
    schema.write_text("""source: raw is duckdb.table('numbers.csv') extend {
  view: entries is { select: value order_by: value }
}
""")
    base.write_text("import '../shared/schema.malloy'\nsource: numbers is raw\n")
    root = authored / "analysis.malloynb"
    original = """>>>markdown
# Numbers £
>>>malloy
##! experimental.givens
import 'models/base.malloy'
given: minimum :: number
source: visible is numbers
run: numbers -> { where: value >= $minimum select: value order_by: value }
>>>markdown
## Total
>>>sql connection:duckdb
SELECT SUM(value) AS total FROM (%{ numbers -> {
  where: value >= $minimum select: value
} }%)
"""
    root.write_text(original)
    inputs = {"minimum": 20}
    document = compile_document(root, profile="native", givens=inputs, data_root=data)
    assert document.profile == "native"
    assert document.source.text == original
    assert set(document.source.imports) == {path.as_uri() for path in (base, schema)}
    assert document == compile_document(
        root, profile="native", givens=inputs, data_root=data
    )
    inputs["minimum"] = 0
    document.givens["minimum"] = 1
    assert document.givens == {"minimum": 20}
    output = tmp_path / ("analysis" + suffix)
    content = renderer.render(document, output_path=output)
    assert content == renderer.render(document, output_path=output)
    output.write_text(content)
    for path in (root, base, schema):
        path.unlink()

    if renderer is marimo:
        values = run_notebook(output)
        model = values["model"]
        try:
            assert values["model_source"].text == original
            assert values["run_1"].to_dicts() == [{"value": 42}]
            assert values["sql_1"].item() == 42
            assert "visible.entries" in model.queries
            assert model.inspect()["native"]["sources"]
            assert model.run(query="run:1", givens={"minimum": 10})[
                "value"
            ].to_list() == [12, 42]
            assert (
                model.run(
                    "run: numbers -> { aggregate: total is value.sum() }",
                    givens=values["givens"],
                ).item()
                == 56
            )
        finally:
            values["session"].close()
    else:
        notebook = json.loads(content)
        assert notebook["metadata"]["pymalloy"]["profile"] == "native"
        execute_notebook(
            output,
            f"""
assert model_source.text == {original!r}
assert run_1.to_dicts() == [{{'value': 42}}]
assert sql_1.item() == 42
assert 'visible.entries' in model.queries
assert model.inspect()['native']['sources']
givens['minimum'] = 10
assert model.run(query='run:1', givens=givens)['value'].to_list() == [12, 42]
assert model.run('run: numbers -> {{ aggregate: total is value.sum() }}', givens=givens).item() == 56
session.close()
""",
            pymalloy=True,
        )


@pytest.mark.parametrize("renderer,suffix", [(marimo, ".py"), (jupyter, ".ipynb")])
def test_hydrated_copy_runs_before_dependent_cells(tmp_path, renderer, suffix):
    source = tmp_path / "copy.malloynb"
    source.write_text(""">>>sql connection:duckdb
COPY (SELECT 42 AS answer) TO 'answer.parquet' (FORMAT PARQUET)
>>>sql
SELECT * FROM 'answer.parquet'
""")
    document = compile_document(source, profile="native")
    output = tmp_path / ("copy" + suffix)
    output.write_text(renderer.render(document, output_path=output))
    if renderer is marimo:
        values = run_notebook(output)
        try:
            assert values["sql_1"].is_empty()
            assert values["sql_2"].item() == 42
        finally:
            values["session"].close()
    else:
        execute_notebook(
            output,
            "assert sql_1.is_empty()\nassert sql_2.item() == 42\nsession.close()",
            pymalloy=True,
        )


def test_source_bundle_is_closed_and_does_not_fall_back_to_original_files(tmp_path):
    imported = tmp_path / "base.malloy"
    imported.write_text("source: numbers is duckdb.sql('SELECT 42 AS value')")
    root = (tmp_path / "model.malloy").as_uri()
    source = ModelSource(
        root, "import 'base.malloy'\nrun: numbers -> { select: value }"
    )
    with Session() as session:
        with pytest.raises(CompilationError, match="Source bundle is missing"):
            session.load_source(source)
        assert (
            session.run(
                "run: duckdb.sql('SELECT 42 AS answer') -> {select: answer}"
            ).item()
            == 42
        )


@pytest.mark.parametrize("borrowed", [False, True])
def test_unreferenced_session_releases_its_resources_after_model_close(borrowed):
    connection = duckdb.connect() if borrowed else None
    session = Session(connection=connection)
    connection = session.connection
    model = session.model("run: duckdb.sql('SELECT 42 AS answer') -> {select: answer}")
    del session
    assert model.run().item() == 42
    model.close()
    gc.collect()
    if borrowed:
        assert connection.execute("SELECT 42").fetchone() == (42,)
        connection.close()
    else:
        with pytest.raises(duckdb.ConnectionException):
            connection.execute("SELECT 42")


@pytest.mark.parametrize("profile", ["precompiled", "native"])
def test_cli_profiles_preserve_selection_and_dependencies(tmp_path, profile):
    database = tmp_path / "data.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE TABLE numbers AS SELECT 42 AS answer")
    source = tmp_path / "answer.malloy"
    source.write_text("run: duckdb.table('numbers') -> { select: answer }")
    output = tmp_path / "answer.ipynb"
    result = subprocess.run(
        [
            "pymalloy",
            "export",
            str(source),
            "--format",
            "jupyter",
            "--profile",
            profile,
            "--database",
            str(database),
            "--query",
            "run:1",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    notebook = json.loads(output.read_text())
    requirements = notebook["metadata"]["pymalloy"]["dependencies"]
    assert notebook["metadata"]["pymalloy"]["profile"] == profile
    if profile == "native":
        assert requirements[0].startswith("pymalloy[server]==")
        execute_notebook(
            output,
            "import duckdb\n"
            "assert run_1.item() == 42\n"
            "try:\n    session.connection.execute('DELETE FROM numbers')\n"
            "except duckdb.InvalidInputException:\n    pass\n"
            "else:\n    raise AssertionError('Expected a read-only connection')\n"
            "session.close()",
            pymalloy=True,
        )
    else:
        assert requirements == ["duckdb>=1.5.5", "polars>=1.44.2"]
        execute_notebook(output, "assert run_1.item() == 42")
