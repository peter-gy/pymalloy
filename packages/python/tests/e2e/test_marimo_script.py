import subprocess
import textwrap
from pathlib import Path

import duckdb
import pytest
from support import run_to_completion

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(240)]

FILTERED = """##! experimental.givens
given: minimum :: number
source: numbers is duckdb.sql('SELECT unnest([2, 12, 42]) AS value')
run: numbers -> { where: value >= $minimum select: value }
"""

COPY = """>>>sql connection:duckdb
COPY (SELECT 42 AS value) TO 'answer.parquet'
>>>sql
SELECT * FROM 'answer.parquet'
"""

PRINT_DEFINITIONS = textwrap.dedent(
    """\
    import importlib.util
    import sys

    path, name = sys.argv[1:]
    spec = importlib.util.spec_from_file_location("exported_report", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _outputs, definitions = module.app.run()
    print(definitions[name].to_dicts())
    """
)


def _export(model: Path, output: Path, *arguments: str) -> None:
    result = subprocess.run(
        [
            "pymalloy",
            "export",
            str(model),
            "--format",
            "marimo",
            "-o",
            str(output),
            *arguments,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert output.is_file()


def _definitions(notebook: Path, name: str, cwd: Path) -> str:
    completed = run_to_completion(
        ["python", "-c", PRINT_DEFINITIONS, str(notebook), name],
        cwd=cwd,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def test_exported_marimo_script_runs_after_the_model_is_gone(tmp_path: Path):
    away = tmp_path / "away"
    away.mkdir()
    for profile in ("precompiled", "native"):
        work = tmp_path / profile
        work.mkdir()
        model = work / "filtered.malloy"
        model.write_text(FILTERED)
        report = work / "report.py"
        _export(
            model,
            report,
            "--profile",
            profile,
            "--givens",
            '{"minimum": 20}',
        )
        assert "run_0" in report.read_text()
        model.unlink()
        completed = run_to_completion(
            ["python", str(report)],
            cwd=away,
            timeout=30,
        )
        assert completed.returncode == 0, completed.stderr
        assert "[{'value': 42}]" in _definitions(report, "run_0", away)

    copy_dir = tmp_path / "copy"
    copy_dir.mkdir()
    notebook = copy_dir / "copy.malloynb"
    notebook.write_text(COPY)
    report = copy_dir / "report.py"
    _export(notebook, report, "--profile", "precompiled")
    notebook.unlink()
    completed = run_to_completion(["python", str(report)], cwd=away, timeout=30)
    assert completed.returncode == 0, completed.stderr
    with duckdb.connect() as connection:
        assert connection.execute(
            "SELECT * FROM read_parquet(?)",
            [str(copy_dir / "answer.parquet")],
        ).fetchall() == [(42,)]
