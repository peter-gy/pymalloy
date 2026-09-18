import os
import subprocess
import sys
import time

import duckdb
import pytest

import pymalloy as pm
from pymalloy import CompilationError, ModelError
from pymalloy.analysis import MarkdownCell, ParseReport, QueryCell


def test_server_uses_packaged_runtime_without_widget_imports_or_project_config(
    tmp_path,
):
    (tmp_path / "deno.json").write_text("invalid configuration")
    (tmp_path / "package.json").write_text("invalid configuration")
    program = """
import importlib.abc
import sys
from pathlib import Path
blocked = {'anywidget', 'ipywidgets', 'traitlets', 'polars', 'pyarrow', 'duckdb'}
class WidgetImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            raise AssertionError(f'Unexpected dependency imported: {fullname}')
sys.meta_path.insert(0, WidgetImports())
import pymalloy as pm
source = "run: duckdb.sql('SELECT 9007199254740993::BIGINT AS id') -> { select: id }"
assert pm.format(source)
blocked.remove('duckdb')
blocked.remove('pyarrow')
model = pm.model(source)
query = model.query()
assert query.run().rows() == [{'id': 9007199254740993}]
assert '9007199254740993' in model.sql()
assert model.inspect().model is not None
assert model.source().text == source
model.close()
assert pm.check(source).diagnostics == []
assert pm.run(pm.format(source)).rows() == [{'id': 9007199254740993}]
Path('answer.malloy').write_text(source)
from pymalloy.export import prepare
assert prepare('answer.malloy').queries[0].name == 'run:0'
"""
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
    model = pm.model(source)
    try:
        assert model.source().text == source
        assert model.run().rows() == [{"value": payload}]
    finally:
        model.close()


def test_tooling_and_documents_return_typed_records_with_explicit_selection():
    source = (
        "source: one is duckdb.sql('SELECT 42 AS value')\nrun: one -> {select:value}"
    )
    parsed = pm.parse(source, url="file:///typed.malloy")
    assert isinstance(parsed, ParseReport)
    assert parsed.symbols[0].name == "one"
    model = pm.model(source)
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


def test_expired_schema_discovery_does_not_start_another_database_request(monkeypatch):
    now = [100.0]
    descriptions = []
    execute = duckdb.DuckDBPyConnection.execute

    def describe(self, sql, *args, **kwargs):
        result = execute(self, sql, *args, **kwargs)
        if sql.startswith("DESCRIBE"):
            descriptions.append(sql)
            now[0] = 102.0
        return result

    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(duckdb.DuckDBPyConnection, "execute", describe)
    with pytest.raises(TimeoutError):
        pm.model(
            "source: a is duckdb.sql('SELECT 1 AS value')\n"
            "source: b is duckdb.sql('SELECT 2 AS value')\nrun: a -> {select:value}",
            timeout=1,
        )
    assert len(descriptions) == 1


def test_model_close_reaps_compiler_process(children):
    model = pm.model("run: duckdb.sql('SELECT 42 AS n') -> {select: n}")
    assert model.run().rows() == [{"n": 42}]
    assert children and all(child.poll() is None for child in children)
    model.close()
    model.close()
    assert all(child.poll() is not None for child in children)


def test_one_shot_execution_releases_resources_on_success_and_failure(children):
    assert pm.run("run: duckdb.sql('SELECT 42 AS n') -> {select:n}").rows() == [
        {"n": 42}
    ]
    assert children and all(child.poll() is not None for child in children)
    with pytest.raises(CompilationError):
        pm.run("run: missing")
    assert all(child.poll() is not None for child in children)


def test_compiler_failure_closes_model_and_preserves_borrowed_connection(children):
    with duckdb.connect() as connection:
        model = pm.model(
            "run: duckdb.sql('SELECT 42 AS n') -> {select:n}", connection=connection
        )
        assert children
        children[0].kill()
        children[0].wait(timeout=5)
        with pytest.raises(ModelError, match="Compiler process"):
            model.run()
        assert model.closed
        model.close()
        assert connection.execute("SELECT 42").fetchone() == (42,)
