import gc
import json
import subprocess

import duckdb
import pytest
from test_compile import run_notebook
from test_jupyter import execute_notebook

import pymalloy as pm
from pymalloy import CompilationError, ModelSource
from pymalloy.export import jupyter, marimo, prepare


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
    schema.write_text(
        """source: raw is duckdb.table('numbers.csv') extend {
  view: entries is { select: value order_by: value }
}
"""
    )
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
    document = prepare(root, profile="headless", givens=inputs, data_root=data)
    assert document.profile == "headless"
    assert document.source.text == original
    assert set(document.source.imports) == {path.as_uri() for path in (base, schema)}
    assert document == prepare(root, profile="headless", givens=inputs, data_root=data)
    inputs["minimum"] = 0
    with pytest.raises(TypeError):
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
            assert values["run_0"].to_dicts() == [{"value": 42}]
            assert values["sql_0"].item() == 42
            assert "visible.entries" in [q.name for q in model.queries]
            assert model.inspect().model.sources
            assert model.query("run:0").run(givens={"minimum": 10}).polars()[
                "value"
            ].to_list() == [12, 42]
            assert (
                model.query(
                    malloy="run: numbers -> { aggregate: total is value.sum() }"
                )
                .run(givens=values["givens"])
                .polars()
                .item()
                == 56
            )
        finally:
            values["model"].close()
    else:
        notebook = json.loads(content)
        assert notebook["metadata"]["pymalloy"]["profile"] == "headless"
        execute_notebook(
            output,
            f"\nassert model_source.text == {original!r}\nassert run_0.to_dicts() == [{{'value': 42}}]\nassert sql_0.item() == 42\nassert 'visible.entries' in [q.name for q in model.queries]\nassert model.inspect().model.sources\ngivens['minimum'] = 10\nassert model.query('run:0').run(givens=givens).polars()['value'].to_list() == [12, 42]\nassert model.query(malloy='run: numbers -> {{ aggregate: total is value.sum() }}').run(givens=givens).polars().item() == 56\nmodel.close()\n",
            pymalloy=True,
        )


@pytest.mark.parametrize("renderer,suffix", [(marimo, ".py"), (jupyter, ".ipynb")])
def test_hydrated_copy_runs_before_dependent_cells(tmp_path, renderer, suffix):
    source = tmp_path / "copy.malloynb"
    source.write_text(
        """>>>sql connection:duckdb
COPY (SELECT 42 AS answer) TO 'answer.parquet' (FORMAT PARQUET)
>>>sql
SELECT * FROM 'answer.parquet'
"""
    )
    document = prepare(source, profile="headless")
    output = tmp_path / ("copy" + suffix)
    output.write_text(renderer.render(document, output_path=output))
    if renderer is marimo:
        values = run_notebook(output)
        try:
            assert values["sql_0"].is_empty()
            assert values["sql_1"].item() == 42
        finally:
            values["model"].close()
    else:
        execute_notebook(
            output,
            "assert sql_0.is_empty()\nassert sql_1.item() == 42\nmodel.close()",
            pymalloy=True,
        )


def test_source_bundle_is_closed_and_does_not_fall_back_to_original_files(tmp_path):
    imported = tmp_path / "base.malloy"
    imported.write_text("source: numbers is duckdb.sql('SELECT 42 AS value')")
    root = (tmp_path / "model.malloy").as_uri()
    source = ModelSource(
        root,
        "import 'base.malloy'\nrun: numbers -> { select: value }",
    )
    with pytest.raises(CompilationError, match="Source bundle is missing"):
        pm.model(source)
    assert (
        pm.run("run: duckdb.sql('SELECT 42 AS answer') -> {select: answer}")
        .polars()
        .item()
        == 42
    )


@pytest.mark.parametrize("borrowed", [False, True])
def test_query_retains_model_resources_until_it_is_released(borrowed):
    connection = duckdb.connect() if borrowed else None
    model = pm.model(
        "run: duckdb.sql('SELECT 42 AS answer') -> {select:answer}",
        connection=connection,
    )
    connection = model.connection
    query = model.query()
    del model
    gc.collect()
    assert query.run().rows() == [{"answer": 42}]
    del query
    gc.collect()
    if borrowed:
        assert connection.execute("SELECT 42").fetchone() == (42,)
        connection.close()
    else:
        with pytest.raises(duckdb.ConnectionException):
            connection.execute("SELECT 42")


@pytest.mark.parametrize("profile", ["precompiled", "headless"])
def test_cli_profiles_preserve_selection_title_and_readonly_access(tmp_path, profile):
    database = tmp_path / "data.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE TABLE numbers AS SELECT 42 AS answer")
    source = tmp_path / "answer.malloy"
    source.write_text(
        "source: numbers is duckdb.table('numbers') extend {view: entries is {select:answer}}\n"
        "query: selected is numbers -> entries\nrun: selected"
    )
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
            "selected",
            "--query",
            "numbers.entries",
            "--title",
            "Answer report",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    notebook = json.loads(output.read_text())
    assert notebook["metadata"]["title"] == "Answer report"
    requirements = notebook["metadata"]["pymalloy"]["dependencies"]
    assert notebook["metadata"]["pymalloy"]["profile"] == profile
    if profile == "headless":
        assert requirements[0].startswith("pymalloy[headless]==")
        assert requirements[1:] == ["polars>=1.44"]
        execute_notebook(
            output,
            """import duckdb
assert selected.item() == 42
assert numbers_entries.item() == 42
try:
    model.connection.execute('DELETE FROM numbers')
except duckdb.InvalidInputException:
    pass
else:
    raise AssertionError('Expected a read-only connection')
model.close()""",
            pymalloy=True,
        )
    else:
        assert requirements == ["duckdb>=1.5", "polars>=1.44"]
        execute_notebook(
            output,
            """assert selected.item() == 42
assert numbers_entries.item() == 42
with connect() as connection:
    try:
        connection.execute('DELETE FROM numbers')
    except duckdb.InvalidInputException:
        pass
    else:
        raise AssertionError('Expected a read-only connection')
with duckdb.connect(str(database)) as writable:
    assert writable.execute('SELECT answer FROM numbers').fetchone() == (42,)
""",
        )


@pytest.mark.parametrize("profile", ["headless", "widget"])
def test_notebook_preserves_configured_connection_name(tmp_path, profile):
    path = tmp_path / "model.malloy"
    path.write_text("run: warehouse.sql('SELECT 42 AS value') -> { select: value }")
    document = prepare(path, profile=profile, connection_name="warehouse")
    assert document.connection_name == "warehouse"
    output = tmp_path / "report.py"
    output.write_text(marimo.render(document, output_path=output))
    values = run_notebook(output)
    if profile == "headless":
        try:
            assert values["run_0"].to_dicts() == [{"value": 42}]
        finally:
            values["model"].close()
    else:
        widget = values["run_0"]
        try:
            assert widget.connection_name == "warehouse"
        finally:
            widget.close()


@pytest.mark.parametrize("profile", ["precompiled", "headless", "widget"])
@pytest.mark.parametrize("reader", [False, True], ids=["table", "sql-reader"])
def test_http_inputs_survive_notebook_relocation(
    tmp_path, monkeypatch, profile, reader
):
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    served = tmp_path / "served"
    served.mkdir()
    (served / "rows.csv").write_text("value\n42\n")

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_HEAD(self):
            if self.path == "/redirect.csv":
                self.send_response(302)
                self.send_header("Location", "/rows.csv")
                self.end_headers()
            else:
                super().do_HEAD()

        def do_GET(self):
            if self.path == "/redirect.csv":
                self.send_response(302)
                self.send_header("Location", "/rows.csv")
                self.end_headers()
            else:
                super().do_GET()

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(Handler, directory=str(served))
    )
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/redirect.csv"
        table = pm.sql(f"SELECT * FROM read_csv('{url}')") if reader else pm.table(url)
        source = (
            pm.draft()
            .define(rows=table)
            .queries(answer=pm.ref("rows").pipe(pm.query(pm.select(pm.col("value")))))
        )
        path = tmp_path / "model.malloy"
        path.write_text(source.text)
        document = prepare(path, profile=profile, remote_files=[url] if reader else ())
        assert document.remote_files == (url,)
        original = tmp_path / "original"
        original.mkdir()
        output = original / "report.py"
        output.write_text(marimo.render(document, output_path=output))
        relocated = tmp_path / "relocated"
        original.rename(relocated)
        path.unlink()
        monkeypatch.chdir(relocated)
        values = run_notebook(relocated / "report.py")
        if profile == "widget":
            widget = values["answer"]
            try:
                assert url in widget.source.text
            finally:
                widget.close()
        else:
            try:
                assert values["answer"].to_dicts() == [{"value": 42}]
            finally:
                if profile == "headless":
                    values["model"].close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.mark.parametrize("profile", ["precompiled", "headless"])
def test_explicit_native_extensions_survive_notebook_export(tmp_path, profile):
    path = tmp_path / "extensions.malloy"
    path.write_text(
        "run: duckdb.sql(\"SELECT current_setting('http_keep_alive') IS NOT NULL AS loaded\") -> { select: loaded }"
    )
    document = prepare(path, profile=profile, extensions=["httpfs", "httpfs"])
    assert document.extensions == ("httpfs",)
    assert document.remote_files == ()
    output = tmp_path / "report.py"
    output.write_text(marimo.render(document, output_path=output))
    values = run_notebook(output)
    try:
        assert values["run_0"].to_dicts() == [{"loaded": True}]
    finally:
        if profile == "headless":
            values["model"].close()
