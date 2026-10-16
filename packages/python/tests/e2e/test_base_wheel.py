import json
from pathlib import Path

import pytest
from support import run_in_venv

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(600)]

NATIVE_PROGRAM = """
import duckdb
import pyarrow as pa

from pymalloy import MalloyWidget

widget = MalloyWidget("run: example")
if widget.state["status"] != "idle":
    raise SystemExit(widget.state["status"])
widget.close()

import pymalloy.agent as agent

skill = agent.agent_skill()
if "# PyMalloy model authoring" not in skill.file("SKILL.md").read_text():
    raise SystemExit("SKILL.md")
if "# Modeling practices" not in skill.file("references/modeling.md").read_text():
    raise SystemExit("modeling.md")

import pymalloy as pm
import subprocess

def launch(*args, **kwargs):
    raise AssertionError("Compilation launched a child process")
subprocess.Popen = launch

source = "source: numbers is duckdb.sql('SELECT 42 AS value')"
assert pm.parse(source).symbols[0].name == "numbers"
formatted = pm.format(source)
assert pm.format(formatted) == formatted

captured = pm.data(pa.table({"value": [20, 22]}))
candidate = pm.draft().sources(numbers=captured).queries(
    total=pm.source("numbers").pipe(pm.view().aggregate(value=pm.col("value").sum()))
)
with duckdb.connect() as native, pm.connect(native) as connection:
    with connection.model(candidate) as model:
        assert model.query("total").run().to_pylist() == [{"value": 42}]
    assert native.execute("SELECT 42").fetchone() == (42,)
"""


def test_default_wheel_installs_cli_commands(tmp_path: Path, native_venv: Path):
    for command in (("--help",), ("export", "--help"), ("check", "--help")):
        result = run_in_venv(native_venv, "pymalloy", *command, cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        assert "usage:" in result.stdout


def test_default_wheel_exports_jupyter_notebooks(tmp_path: Path, native_venv: Path):
    model = tmp_path / "model.malloy"
    model.write_text("run: duckdb.sql('SELECT 1 AS value') -> { select: value }\n")
    output = tmp_path / "out.ipynb"
    exported = run_in_venv(
        native_venv,
        "pymalloy",
        "export",
        str(model),
        "--format",
        "jupyter",
        "-o",
        str(output),
        cwd=tmp_path,
        timeout=30,
    )
    assert exported.returncode == 0, exported.stderr
    assert exported.stdout == ""
    assert str(output) in exported.stderr
    assert json.loads(output.read_text())["nbformat"] == 4


def test_default_wheel_executes_captured_data(tmp_path: Path, native_venv: Path):
    program = run_in_venv(
        native_venv, "python", "-c", NATIVE_PROGRAM, cwd=tmp_path, timeout=30
    )
    assert program.returncode == 0, program.stderr
    assert program.stdout == ""
