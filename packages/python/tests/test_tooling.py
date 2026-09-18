import json
import subprocess
import sys

import pytest

from pymalloy.analysis import Position
from pymalloy.server import CompilationError, Session

ONE = "run: duckdb.sql('SELECT 42 AS value') -> { select: value }"


def cli(*arguments):
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from pymalloy.cli import main; main()",
            *map(str, arguments),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_semantic_diagnostics_preserve_codepoint_ranges_and_repair(tmp_path):
    source = "run: duckdb.sql(\"SELECT '😀' AS label\") -> { select: missing }"
    path = tmp_path / "unicode.malloy"
    with Session() as session:
        report = session.check(source, path=path)
        assert not report.ok
        diagnostic = next(
            item for item in report.diagnostics if item.code == "field-not-found"
        )
        assert diagnostic.severity == "error"
        assert diagnostic.location.url == path.as_uri()
        assert diagnostic.location.range.start == Position(0, source.index("missing"))
        assert diagnostic.location.range.end == Position(0, source.index("missing") + 7)
        repaired = source.replace("select: missing", "select: label")
        assert session.check(repaired, path=path).ok
        assert session.run(repaired).to_dicts() == [{"label": "😀"}]
        with pytest.raises(CompilationError) as caught:
            session.model(source)
        assert caught.value.diagnostics[0].code == "field-not-found"
        assert session.run(ONE).item() == 42


def test_check_file_reports_diagnostics_in_imported_source(tmp_path):
    imported = tmp_path / "base.malloy"
    imported.write_text(
        "source: numbers is duckdb.sql('SELECT 1 AS value') extend { dimension: broken is missing }"
    )
    root = tmp_path / "report.malloy"
    root.write_text("import 'base.malloy'\nrun: numbers -> { select: value }")
    with Session() as session:
        report = session.check_file(root)
    assert not report.ok
    diagnostic = next(
        item for item in report.diagnostics if item.code == "field-not-found"
    )
    assert diagnostic.location.url == imported.as_uri()
    assert diagnostic.location.range.start.line == 0
    assert report.imports[0]["url"] == imported.as_uri()


def test_syntax_check_describes_missing_data_without_resolving_it(tmp_path):
    source = "import 'absent.malloy'\nsource: rows is duckdb.table('absent.csv')"
    with Session(data_root=tmp_path) as session:
        syntax = session.check(
            source, path=tmp_path / "report.malloy", syntax_only=True
        )
        semantic = session.check(source, path=tmp_path / "report.malloy")
    assert syntax.ok
    assert syntax.native.model is None
    assert syntax.queries == ()
    assert syntax.tables[0]["connection"] == "duckdb"
    assert syntax.tables[0]["path"] == "absent.csv"
    assert syntax.imports[0]["url"] == (tmp_path / "absent.malloy").as_uri()
    assert not semantic.ok


def test_document_check_maps_multiline_embedded_diagnostics(tmp_path):
    path = tmp_path / "report.malloynb"
    source = """>>>markdown
# Results
>>>malloy
source: numbers is duckdb.sql('SELECT 42 AS value')
>>>sql connection:duckdb
SELECT * FROM %{
  missing_source -> { select: * }
}%"""
    path.write_text(source)
    with Session() as session:
        report = session.check_file(path)
    assert not report.ok
    diagnostic = next(
        item for item in report.diagnostics if item.code == "source-or-query-not-found"
    )
    assert diagnostic.location.url == path.as_uri()
    assert diagnostic.location.range.start == Position(6, 2)
    assert diagnostic.location.range.end == Position(6, 16)


def test_native_warning_contains_a_source_replacement():
    source = (
        "run: duckdb.sql('SELECT 1 AS value') -> { where: value = null select: value }"
    )
    with Session() as session:
        report = session.check(source)
        assert report.ok
        warning = next(
            item for item in report.diagnostics if item.severity == "warning"
        )
        assert warning.replacement == "value is null"
        at = warning.location.range
        assert source[at.start.character : at.end.character] == "value = null"
        repaired = (
            source[: at.start.character]
            + warning.replacement
            + source[at.end.character :]
        )
        assert session.check(repaired).diagnostics == ()


def test_native_completions_and_help_have_source_context():
    source = "source: numbers is duckdb.table('absent.csv')\nrun: numbers -> {\n  group_by: value\n  \n}"
    with Session() as session:
        report = session.check(source, syntax_only=True, position=Position(3, 2))
        context = session.check(source, syntax_only=True, position=Position(2, 3))
    assert any(item["text"] == "group_by: " for item in report.completions)
    assert context.help == {"type": "query_property", "token": "group_by:"}
    assert report.symbols[0]["name"] == "numbers"


def test_model_inspection_exposes_givens_schemas_and_references(tmp_path):
    source = """##! experimental.givens
given: cutoff :: number is 10
source: numbers is duckdb.sql('SELECT 42 AS value') extend {
  view: filtered is { where: value > $cutoff select: value }
}
run: numbers -> filtered
"""
    path = tmp_path / "numbers.malloy"
    path.write_text(source)
    with Session() as session, session.load(path) as model:
        inspection = model.inspect()
        selected = model.inspect(position=Position(5, 6))
        assert model.run().item() == 42
    assert inspection["queries"] == ["run:1", "numbers.filtered"]
    entry = inspection["native"]["model"]["entries"][0]
    assert entry["kind"] == "source"
    assert entry["name"] == "numbers"
    assert entry["schema"]["fields"][0] == {
        "kind": "dimension",
        "name": "value",
        "type": {"kind": "number_type", "subtype": "integer"},
    }
    given = inspection["givens"][0]
    assert given["name"] == "cutoff"
    assert given["type"] == "number"
    assert given["default_text"] == "10"
    assert given["required"] is False
    assert inspection["diagnostics"] == []
    assert selected["reference"]["text"] == "numbers"
    assert selected["reference"]["definition_location"]["url"] == path.as_uri()
    assert selected["reference"]["definition_location"]["range"]["start"] == {
        "line": 2,
        "character": 8,
    }
    json.dumps(inspection)


def test_inspection_follows_import_targets_and_references(tmp_path):
    imported = tmp_path / "base.malloy"
    imported.write_text(
        "source: numbers is duckdb.sql('SELECT 42 AS value')\nquery: total is numbers -> { aggregate: total is value.sum() }"
    )
    root = tmp_path / "report.malloy"
    root.write_text("import 'base.malloy'\nrun: total")
    with Session() as session, session.load(root) as model:
        imported_at = model.inspect(position=Position(0, 10))
        reference = model.inspect(position=Position(1, 17), url=imported.as_uri())
    assert imported.as_uri() in imported_at["dependencies"]
    assert imported_at["import"]["url"] == imported.as_uri()
    assert reference["reference"]["text"] == "numbers"
    assert reference["reference"]["definition_location"]["url"] == imported.as_uri()
    assert reference["reference"]["definition_location"]["range"]["start"]["line"] == 0


def test_sql_resolves_file_bindings_and_leaves_execution_to_the_caller(tmp_path):
    model_path = tmp_path / "write.malloysql"
    model_path.write_text(
        ">>>sql connection:duckdb\nCOPY (SELECT 42 AS value) TO 'values.csv' (HEADER)\n"
    )
    output = tmp_path / "values.csv"
    with Session(data_root=tmp_path) as session, session.load(model_path) as model:
        sql = model.sql(query="sql:1")
        assert not output.exists()
        session.connection.execute(sql)
    assert output.read_text() == "value\n42\n"


def test_format_roundtrip_preserves_execution_and_reports_malformed_source():
    with Session() as session:
        formatted = session.format(ONE)
        assert session.format(formatted) == formatted
        assert session.check(formatted).ok
        assert session.run(formatted).item() == 42
        with pytest.raises(CompilationError) as caught:
            session.format("run: ->")
        assert caught.value.diagnostics[0].code == "syntax-error"
        assert caught.value.diagnostics[0].location.range.start.line == 0


def test_cli_check_returns_json_diagnostics_and_preserves_source(tmp_path):
    path = tmp_path / "model.malloy"
    source = "run: duckdb.sql('SELECT 1 AS value') -> { select: missing }"
    path.write_text(source)
    result = cli("check", path, "--json")
    assert result.returncode == 1
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert not report["ok"]
    assert report["url"] == path.as_uri()
    assert report["diagnostics"][0]["code"] == "field-not-found"
    assert path.read_text() == source
    path.write_text(ONE)
    good = cli("check", path, "--json")
    assert good.returncode == 0
    assert json.loads(good.stdout)["ok"]


def test_cli_syntax_check_accepts_an_unavailable_data_source(tmp_path):
    path = tmp_path / "model.malloy"
    path.write_text("source: rows is duckdb.table('absent.csv')")
    result = cli("check", path, "--syntax-only", "--json", "--data-root", tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout)["tables"][0]["path"] == "absent.csv"


def test_cli_formatter_emits_source_and_checks_without_writing(tmp_path):
    path = tmp_path / "model.malloy"
    path.write_text(ONE)
    result = cli("format", path)
    assert result.returncode == 0
    assert result.stderr == ""
    assert path.read_text() == ONE
    assert result.stdout != ONE
    assert cli("format", path, "--check").returncode == 1
    path.write_text(result.stdout)
    checked = cli("format", path, "--check")
    assert checked.returncode == 0
    assert checked.stdout == ""
    assert path.read_text() == result.stdout
    crlf = result.stdout.replace("\n", "\r\n").encode("utf-8")
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


def test_invalid_tool_arguments_leave_session_available():
    with Session() as session, session.model(ONE) as model:
        calls = [
            lambda: session.check(ONE, syntax_only=1),
            lambda: session.run(ONE, query={}),
            lambda: model.run(query={}),
            lambda: model.sql(query={}),
            lambda: model.inspect(position=Position(0, 5), url={}),
        ]
        for call in calls:
            with pytest.raises(TypeError):
                call()
            assert session.run(ONE).item() == 42


def test_required_givens_leave_source_metadata_available_before_execution():
    source = """##! experimental.givens
given: cutoff :: number
source: numbers is duckdb.sql('SELECT 42 AS value')
run: numbers -> { where: value > $cutoff select: value }
"""
    with Session() as session:
        report = session.check(source)
        assert report.ok
        assert report.native.model is None
        assert report.queries == ("run:1",)
        assert report.native.sources[0]["name"] == "numbers"
        with session.model(source) as model:
            inspection = model.inspect()
            assert inspection["native"]["model"] is None
            assert inspection["native"]["sources"][0]["name"] == "numbers"
            assert inspection["givens"][0]["name"] == "cutoff"
            assert inspection["givens"][0]["default_text"] is None
            sql = model.sql(givens={"cutoff": 10})
            assert session.connection.sql(sql).fetchone() == (42,)


def test_cli_check_reports_database_setup_errors(tmp_path):
    source = tmp_path / "model.malloy"
    source.write_text(ONE)
    database = tmp_path / "invalid.duckdb"
    database.write_text("invalid database contents")
    result = cli("check", source, "--database", database)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("pymalloy:")
