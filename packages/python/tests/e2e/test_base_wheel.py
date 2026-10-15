from pathlib import Path

import pytest
from support import run_in_venv

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(600)]

BASE_PROGRAM = """
import importlib

for name in ("duckdb", "deno"):
    try:
        importlib.import_module(name)
    except ModuleNotFoundError as error:
        if error.name != name:
            raise
    else:
        raise SystemExit(f"{name} imported")

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

try:
    pm.connect()
except ImportError as error:
    if "pymalloy[headless]" not in str(error):
        raise SystemExit(str(error))
else:
    raise SystemExit("connect succeeded")
"""


def test_base_wheel_installs_widget_cli_and_skill_without_duckdb(
    tmp_path: Path, base_venv: Path
):
    home = tmp_path / "home"
    home.mkdir()
    for command in (("--help",), ("export", "--help"), ("check", "--help")):
        result = run_in_venv(base_venv, "pymalloy", *command, cwd=home)
        assert result.returncode == 0, result.stderr
        assert "usage:" in result.stdout

    model = home / "model.malloy"
    model.write_text("run: duckdb.sql('SELECT 1 AS value') -> { select: value }\n")
    output = home / "out.py"
    exported = run_in_venv(
        base_venv,
        "pymalloy",
        "export",
        str(model),
        "--format",
        "marimo",
        "-o",
        str(output),
        cwd=home,
        timeout=30,
    )
    assert exported.returncode == 1
    assert exported.stdout == ""
    assert "pymalloy[headless]" in exported.stderr
    assert not output.exists()

    program = run_in_venv(base_venv, "python", "-c", BASE_PROGRAM, cwd=home, timeout=30)
    assert program.returncode == 0, program.stderr
    assert program.stdout == ""
