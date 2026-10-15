import json
from pathlib import Path

import pytest
from support import run_in_venv

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(600)]

NUMBERS = """##! experimental.givens
given: minimum :: number
run: duckdb.sql('SELECT unnest([2, 42]) AS value') -> { where: value >= $minimum select: value }
"""


def test_headless_wheel_runs_and_rebuilds_from_the_sdist(
    tmp_path: Path, headless_venv: Path, sdist_venv: Path
):
    for venv in (headless_venv, sdist_venv):
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
