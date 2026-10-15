import os
import subprocess
import sys

import duckdb
import pytest

import pymalloy as pm
from pymalloy.analysis import MarkdownCell, ParseReport, QueryCell
from pymalloy.errors import CompilationError


def test_headless_uses_packaged_runtime_without_widget_imports_or_project_config(
    tmp_path,
):
    (tmp_path / "deno.json").write_text("invalid configuration")
    (tmp_path / "package.json").write_text("invalid configuration")
    program = "\nimport importlib.abc\nimport sys\nfrom pathlib import Path\nblocked = {'anywidget', 'ipywidgets', 'traitlets', 'polars', 'pyarrow', 'duckdb'}\nclass WidgetImports(importlib.abc.MetaPathFinder):\n    def find_spec(self, fullname, path=None, target=None):\n        if fullname.split('.')[0] in blocked:\n            raise AssertionError(f'Unexpected dependency imported: {fullname}')\nsys.meta_path.insert(0, WidgetImports())\nimport pymalloy as pm\nsource = \"run: duckdb.sql('SELECT 9007199254740993::BIGINT AS id') -> { select: id }\"\nassert pm.format(source)\nblocked.remove('duckdb')\nblocked.remove('pyarrow')\nmodel = pm.connect().model(source)\nquery = model.query()\nassert query.run().to_pylist() == [{'id': 9007199254740993}]\nassert '9007199254740993' in model.query().sql()\nassert model.inspect().model is not None\nassert model.source().text == source\nmodel.close()\nassert pm.connect().check(source).diagnostics == ()\nassert pm.connect().model(pm.format(source)).query().run().to_pylist() == [{'id': 9007199254740993}]\nPath('answer.malloy').write_text(source)\nfrom pymalloy.export import prepare\nassert prepare('answer.malloy').queries[0].name == 'run:0'\n"
    subprocess.run(
        [sys.executable, "-c", program],
        cwd=tmp_path,
        env={**os.environ, "PATH": "", "DENO_DIR": str(tmp_path / "deno-cache")},
        check=True,
        timeout=30,
    )


def test_compiler_frames_preserve_large_unicode_source_and_replies():
    payload = "λ😀" * 20_000
    source = (
        f'''run: duckdb.sql("""SELECT '{payload}' AS value""") -> {{ select: value }}'''
    )
    model = pm.connect().model(source)
    try:
        assert model.source().text == source
        assert model.query().run().to_pylist() == [{"value": payload}]
    finally:
        model.close()


def test_tooling_and_documents_return_typed_records_with_explicit_selection():
    source = (
        "source: one is duckdb.sql('SELECT 42 AS value')\nrun: one -> {select:value}"
    )
    parsed = pm.parse(source, url="file:///typed.malloy")
    assert isinstance(parsed, ParseReport)
    assert parsed.symbols[0].name == "one"
    model = pm.connect().model(source)
    try:
        default = model.document()
        assert len(default) == 1 and isinstance(default[0], QueryCell)
        assert default[0].name == "run:0"
        inventory = model.document(queries=[])
        assert len(inventory) == 1 and isinstance(inventory[0], MarkdownCell)
        assert "`one`" in inventory[0].text
        with pytest.raises(ValueError, match="query names or all"):
            model.document(queries=[], all=True)
        with pytest.raises(TypeError, match="sequence"):
            model.document(queries="run:0")
    finally:
        model.close()


def test_model_close_reaps_compiler_process(children):
    model = pm.connect().model("run: duckdb.sql('SELECT 42 AS n') -> {select: n}")
    assert model.query().run().to_pylist() == [{"n": 42}]
    assert children and all(child.poll() is None for child in children)
    model.close()
    model.close()
    assert all(child.poll() is not None for child in children)


def test_one_shot_execution_releases_resources_on_success_and_failure(children):
    assert pm.connect().model(
        "run: duckdb.sql('SELECT 42 AS n') -> {select:n}"
    ).query().run().to_pylist() == [{"n": 42}]
    assert children and all(child.poll() is not None for child in children)
    with pytest.raises(CompilationError):
        pm.connect().model("run: missing").query().run()
    assert all(child.poll() is not None for child in children)


def test_compiler_failure_closes_model_and_preserves_borrowed_connection(children):
    with duckdb.connect() as connection:
        model = pm.connect(database=connection).model(
            "run: duckdb.sql('SELECT 42 AS n') -> {select:n}"
        )
        assert children
        children[0].kill()
        children[0].wait(timeout=5)
        with pytest.raises(pm.errors.CompilerError, match="Compiler process"):
            model.query().run()
        assert model.closed
        model.close()
        assert connection.execute("SELECT 42").fetchone() == (42,)
