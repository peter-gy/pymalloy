import json
import os
import sys
from pathlib import Path

import pytest
from support import executable, isolated_env, run_command, run_in_venv

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(600)]

NUMBERS = """##! experimental.givens
given: minimum :: number
run: duckdb.sql('SELECT unnest([2, 42]) AS value') -> { where: value >= $minimum select: value }
"""


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS filesystem sandbox")
def test_native_distributions_run_with_build_cache_inaccessible(
    tmp_path: Path, native_venv: Path, sdist_venv: Path
):
    cargo_home = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo")).resolve()
    policy = (
        '(version 1)(allow default)(deny file-read* (subpath (param "CARGO_HOME")))'
    )
    program = """
import pymalloy as pm

text = "run: duckdb.sql('SELECT 42 AS amount') -> {select: amount}"
assert pm.parse(text).ok
assert pm.format(pm.format(text)) == pm.format(text)
with pm.connect() as connection:
    with connection.model(text) as model:
        assert model.query().run().to_pylist() == [{"amount": 42}]
"""
    for venv in (native_venv, sdist_venv):
        result = run_command(
            [
                "sandbox-exec",
                "-D",
                f"CARGO_HOME={cargo_home}",
                "-p",
                policy,
                str(executable(venv, "python")),
                "-c",
                program,
            ],
            cwd=tmp_path,
            env=isolated_env(venv),
            timeout=60,
        )
        assert result.returncode == 0, result.stderr


def test_native_wheel_runs_and_rebuilds_from_the_sdist(
    tmp_path: Path, native_venv: Path, sdist_venv: Path
):
    for venv in (native_venv, sdist_venv):
        home = tmp_path / venv.parent.name
        home.mkdir()
        model = home / "numbers.malloy"
        model.write_text(NUMBERS)
        ran = run_in_venv(
            venv,
            "pymalloy",
            "run",
            str(model),
            "--givens",
            '{"minimum": 20}',
            cwd=home,
            timeout=60,
        )
        assert ran.returncode == 0, ran.stderr
        assert ran.stdout == '[{"value": 42}]\n'
        assert ran.stderr == ""
        checked = run_in_venv(
            venv,
            "pymalloy",
            "check",
            str(model),
            "--json",
            cwd=home,
            timeout=60,
        )
        assert checked.returncode == 0, checked.stderr
        assert checked.stderr == ""
        assert json.loads(checked.stdout)["ok"] is True
