import importlib.metadata
import json
import subprocess
from pathlib import Path

import pytest
from support import REPO

pytestmark = pytest.mark.e2e

EXAMPLES = REPO / "examples"
ONE = "run: duckdb.sql('SELECT 42 AS value') -> { select: value }"


def cli(*arguments: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["pymalloy", *map(str, arguments)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_cli_version_and_run_bind_parameters(tmp_path: Path):
    version = cli("--version")
    assert version.returncode == 0, version.stderr
    assert version.stderr == ""
    assert (
        version.stdout.strip() == f"pymalloy {importlib.metadata.version('pymalloy')}"
    )
    path = tmp_path / "numbers.malloy"
    path.write_text(
        "##! experimental.givens\n"
        "given: minimum :: number\n"
        "run: duckdb.sql('SELECT unnest([2, 42]) AS value') -> "
        "{ where: value >= $minimum select: value }"
    )
    result = cli("run", path, "--givens", '{"minimum": 20}')
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == '[{"value": 42}]\n'


def test_cli_run_encodes_decimal_temporal_and_exact_integer_values(tmp_path: Path):
    source = tmp_path / "values.malloysql"
    source.write_text(
        ">>>sql connection:duckdb\n"
        "SELECT 1.2300::DECIMAL(12,4) AS amount, DATE '2026-01-02' AS day, "
        "TIMESTAMP '2026-01-02 03:04:05' AS moment, 9007199254740993::BIGINT AS id"
    )
    result = cli("run", source)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    row = json.loads(result.stdout)[0]
    assert row == {
        "amount": "1.2300",
        "day": "2026-01-02",
        "moment": "2026-01-02 03:04:05",
        "id": 9007199254740993,
    }
    assert isinstance(row["id"], int)
    assert isinstance(row["amount"], str)


def test_cli_check_returns_json_diagnostics_and_preserves_source(tmp_path: Path):
    path = tmp_path / "model.malloy"
    source = "run: duckdb.sql('SELECT 1 AS value') -> { select: missing }"
    path.write_text(source)
    result = cli("check", path, "--json")
    assert result.returncode == 1
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert report["ok"] is False
    assert report["url"] == path.as_uri()
    assert report["diagnostics"][0]["code"] == "field-not-found"
    assert path.read_text() == source
    path.write_text(ONE)
    good = cli("check", path, "--json")
    assert good.returncode == 0, good.stderr
    assert good.stderr == ""
    assert json.loads(good.stdout)["ok"] is True


def test_cli_syntax_only_ignores_a_corrupt_database(tmp_path: Path):
    source = tmp_path / "model.malloy"
    source.write_text("run: duckdb.table('absent.csv') -> {select: *}")
    database = tmp_path / "corrupt.duckdb"
    database.write_bytes(b"not a database")
    result = cli(
        "check",
        source,
        "--syntax-only",
        "--database",
        database,
        "--json",
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout)["diagnostics"] == []
    assert database.read_bytes() == b"not a database"


def test_cli_check_reports_database_setup_errors(tmp_path: Path):
    source = tmp_path / "model.malloy"
    source.write_text(ONE)
    database = tmp_path / "invalid.duckdb"
    database.write_text("invalid database contents")
    result = cli("check", source, "--database", database)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("pymalloy:")


def test_cli_formatter_emits_source_and_checks_without_writing(tmp_path: Path):
    path = tmp_path / "model.malloy"
    path.write_text(ONE)
    result = cli("format", path)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert path.read_text() == ONE
    assert result.stdout != ONE
    assert cli("format", path, "--check").returncode == 1
    path.write_text(result.stdout)
    checked = cli("format", path, "--check")
    assert checked.returncode == 0
    assert checked.stdout == ""
    assert path.read_text() == result.stdout
    crlf = result.stdout.replace("\n", "\r\n").encode()
    path.write_bytes(crlf)
    assert cli("format", path, "--check").returncode == 1
    assert path.read_bytes() == crlf
    path.write_text("run: ->")
    failed = cli("format", path)
    assert failed.returncode == 1
    assert failed.stdout == ""
    assert "syntax-error" in failed.stderr
    assert str(path) in failed.stderr
    assert path.read_text() == "run: ->"


def test_cli_export_reports_success_on_stderr(tmp_path: Path):
    source = tmp_path / "values.malloy"
    source.write_text(ONE + "\n")
    output = tmp_path / "report.py"
    result = cli("export", source, "--format", "marimo", "-o", output)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert str(output) in result.stderr
    assert output.stat().st_size > 0


def test_cli_failure_preserves_existing_output(tmp_path: Path):
    output = tmp_path / "report.py"
    output.write_text("existing notebook\n")
    result = cli(
        "export",
        "--format",
        "marimo",
        EXAMPLES / "orders.malloy",
        "--query",
        "missing",
        "-o",
        output,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "Unknown query 'missing'" in result.stderr
    assert "orders.by_region" in result.stderr
    assert output.read_text() == "existing notebook\n"


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        pytest.param(["--givens", "[]"], "givens", id="givens-object"),
        pytest.param(["--givens", "{broken"], "givens", id="givens-json"),
        pytest.param(["--givens", '{"minimum": NaN}'], "givens", id="givens-constant"),
        pytest.param(
            ["--givens", '{"minimum": 1e999}'], "givens", id="givens-overflow"
        ),
        pytest.param(
            ["--files", '["orders.csv"]'],
            "files must be a JSON object",
            id="files-object",
        ),
        pytest.param(
            ["--files", '{"orders.csv": 42}'],
            "files must be a JSON object",
            id="files-path",
        ),
        pytest.param(
            ["--all", "--query", "run:0"],
            "not allowed with argument",
            id="selection-conflict",
        ),
    ],
)
def test_cli_rejects_invalid_export_options_before_replacing_output(
    tmp_path: Path, arguments: list[str], message: str
):
    output = tmp_path / "report.ipynb"
    output.write_text("existing notebook\n")
    result = cli(
        "export",
        EXAMPLES / "orders.malloy",
        "--format",
        "jupyter",
        "--output",
        output,
        *arguments,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert message in result.stderr
    assert output.read_text() == "existing notebook\n"


def test_cli_timeout_stops_check_and_export(tmp_path: Path):
    source = tmp_path / "values.malloy"
    source.write_text(ONE + "\n")
    checked = cli("check", source, "--timeout", "0.001", "--json")
    assert checked.returncode == 1
    assert checked.stdout == ""
    assert "exceeded" in checked.stderr

    output = tmp_path / "report.py"
    output.write_text("existing notebook\n")
    exported = cli(
        "export",
        source,
        "--format",
        "marimo",
        "--timeout",
        "0.001",
        "-o",
        output,
    )
    assert exported.returncode == 1
    assert exported.stdout == ""
    assert output.read_text() == "existing notebook\n"
    assert "exceeded" in exported.stderr
