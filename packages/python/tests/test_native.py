import os
import subprocess
import sys

import duckdb
import pytest

import pymalloy as pm
from pymalloy.analysis import MarkdownCell, ParseReport, QueryCell
from pymalloy.errors import CompilationError


def test_native_compiler_runs_with_external_runtimes_unavailable(tmp_path):
    program = r"""
import importlib.abc
import subprocess
import sys
from pathlib import Path

blocked = {"anywidget", "ipywidgets", "traitlets", "polars", "pyarrow", "duckdb"}
class BaseImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in blocked:
            raise AssertionError(f"Unexpected dependency imported: {fullname}")
sys.meta_path.insert(0, BaseImports())

def launch(*args, **kwargs):
    raise AssertionError("Compilation launched a child process")
subprocess.Popen = launch
import pymalloy as pm
source = "run: duckdb.sql('SELECT 9007199254740993::BIGINT AS id') -> { select: id }"
assert pm.parse(source).ok
assert pm.format(source)
blocked.remove("duckdb")
blocked.remove("pyarrow")
with pm.connect() as connection:
    with connection.model(source) as model:
        assert model.query().run().to_pylist() == [{"id": 9007199254740993}]
        assert "9007199254740993" in model.query().sql()
        assert model.inspect().model is not None
        assert model.source().text == source
    assert connection.check(source).diagnostics == ()
    with connection.model(pm.format(source)) as model:
        assert model.query().run().to_pylist() == [{"id": 9007199254740993}]
Path("answer.malloy").write_text(source)
from pymalloy.export import prepare
assert prepare("answer.malloy").queries[0].name == "run:0"
"""
    subprocess.run(
        [sys.executable, "-c", program],
        cwd=tmp_path,
        env={**os.environ, "PATH": ""},
        check=True,
        timeout=30,
    )


def test_compiler_preserves_large_unicode_source_and_results():
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


def test_model_close_invalidates_retained_queries():
    with pm.connect() as connection:
        model = connection.model("run: duckdb.sql('SELECT 42 AS n') -> {select: n}")
        query = model.query()
        compiler = model._owner._compiler
        result = query.run()
        model.close()
        model.close()
        assert model.closed
        assert compiler.closed
        assert result.to_pylist() == [{"n": 42}]
        with pytest.raises(pm.errors.ClosedError, match="closed"):
            query.run()
        assert connection.duckdb.execute("SELECT 42").fetchone() == (42,)


def test_compilation_diagnostics_leave_the_connection_available():
    with pm.connect() as connection:
        with pytest.raises(CompilationError):
            connection.model("run: missing")
        with connection.model(
            "run: duckdb.sql('SELECT 42 AS n') -> {select:n}"
        ) as model:
            assert model.query().run().to_pylist() == [{"n": 42}]


def test_compiler_failure_closes_model_and_preserves_borrowed_connection():
    with duckdb.connect() as native, pm.connect(native) as connection:
        model = connection.model("run: duckdb.sql('SELECT 42 AS n') -> {select:n}")
        model._owner._compiler.close()
        with pytest.raises(pm.errors.CompilerError, match="closed"):
            model.query().run()
        assert model.closed
        model.close()
        assert native.execute("SELECT 42").fetchone() == (42,)
