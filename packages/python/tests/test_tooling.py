import json
import subprocess
import sys
from contextlib import closing

import pytest

import pymalloy as pm
from pymalloy import CompilationError
from pymalloy.analysis import SourcePosition, to_dict

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
    report = pm.check(source, path=path)
    assert not report.ok
    diagnostic = next(
        item for item in report.diagnostics if item.code == "field-not-found"
    )
    assert diagnostic.severity == "error"
    assert diagnostic.location.url == path.as_uri()
    assert diagnostic.location.range.start == SourcePosition(
        line=0, character=source.index("missing")
    )
    assert diagnostic.location.range.end == SourcePosition(
        line=0, character=source.index("missing") + 7
    )
    repaired = source.replace("select: missing", "select: label")
    assert pm.check(repaired, path=path).ok
    assert pm.run(repaired).polars().to_dicts() == [{"label": "😀"}]
    with pytest.raises(CompilationError) as caught:
        pm.model(source)
    assert caught.value.diagnostics[0].code == "field-not-found"
    assert pm.run(ONE).polars().item() == 42


def test_check_file_reports_diagnostics_in_imported_source(tmp_path):
    imported = tmp_path / "base.malloy"
    imported.write_text(
        "source: numbers is duckdb.sql('SELECT 1 AS value') extend { dimension: broken is missing }"
    )
    root = tmp_path / "report.malloy"
    root.write_text("import 'base.malloy'\nrun: numbers -> { select: value }")
    report = pm.check(root.read_text(), path=root)
    assert not report.ok
    diagnostic = next(
        item for item in report.diagnostics if item.code == "field-not-found"
    )
    assert diagnostic.location.url == imported.as_uri()
    assert diagnostic.location.range.start.line == 0
    assert report.imports[0].url == imported.as_uri()


def test_syntax_check_describes_missing_data_without_resolving_it(tmp_path):
    source = "import 'absent.malloy'\nsource: rows is duckdb.table('absent.csv')"
    syntax = pm.check(
        source, path=tmp_path / "report.malloy", syntax_only=True, data_root=tmp_path
    )
    semantic = pm.check(source, path=tmp_path / "report.malloy", data_root=tmp_path)
    assert syntax.ok
    assert syntax.model.model is None
    assert syntax.queries == []
    assert syntax.tables[0].connection == "duckdb"
    assert syntax.tables[0].path == "absent.csv"
    assert syntax.imports[0].url == (tmp_path / "absent.malloy").as_uri()
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
    report = pm.check(path.read_text(), path=path)
    assert not report.ok
    diagnostic = next(
        item for item in report.diagnostics if item.code == "source-or-query-not-found"
    )
    assert diagnostic.location.url == path.as_uri()
    assert diagnostic.location.range.start == SourcePosition(line=6, character=2)
    assert diagnostic.location.range.end == SourcePosition(line=6, character=16)


def test_headless_warning_contains_a_source_replacement():
    source = (
        "run: duckdb.sql('SELECT 1 AS value') -> { where: value = null select: value }"
    )
    report = pm.check(source)
    assert report.ok
    warning = next(item for item in report.diagnostics if item.severity == "warning")
    assert warning.replacement == "value is null"
    at = warning.location.range
    assert source[at.start.character : at.end.character] == "value = null"
    repaired = (
        source[: at.start.character] + warning.replacement + source[at.end.character :]
    )
    assert pm.check(repaired).diagnostics == []


def test_headless_completions_and_help_have_source_context():
    source = "source: numbers is duckdb.table('absent.csv')\nrun: numbers -> {\n  group_by: value\n  \n}"
    report = pm.check(
        source, syntax_only=True, position=SourcePosition(line=3, character=2)
    )
    context = pm.check(
        source, syntax_only=True, position=SourcePosition(line=2, character=3)
    )
    assert any(item.text == "group_by: " for item in report.completions)
    assert to_dict(context.help) == {"type": "query_property", "token": "group_by:"}
    assert report.symbols[0].name == "numbers"


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
    with closing(pm.model(path)) as model:
        inspection = to_dict(model.inspect())
        selected = to_dict(model.inspect(position=SourcePosition(line=5, character=6)))
        assert model.query().run().polars().item() == 42
    assert [q["name"] for q in inspection["queries"]] == ["run:0", "numbers.filtered"]
    entry = inspection["model"]["model"]["entries"][0]
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
        """source: numbers is duckdb.sql('SELECT 42 AS value')
query: total is numbers -> { aggregate: total is value.sum() }"""
    )
    root = tmp_path / "report.malloy"
    root.write_text("import 'base.malloy'\nrun: total")
    with closing(pm.model(root)) as model:
        imported_at = to_dict(
            model.inspect(position=SourcePosition(line=0, character=10))
        )
        reference = to_dict(
            model.inspect(
                position=SourcePosition(line=1, character=17), url=imported.as_uri()
            )
        )
    assert imported.as_uri() in imported_at["dependencies"]
    assert imported_at["import_"]["url"] == imported.as_uri()
    assert reference["reference"]["text"] == "numbers"
    assert reference["reference"]["definition_location"]["url"] == imported.as_uri()
    assert reference["reference"]["definition_location"]["range"]["start"]["line"] == 0


def test_sql_resolves_file_bindings_and_leaves_execution_to_the_caller(tmp_path):
    model_path = tmp_path / "write.malloysql"
    output = tmp_path / "values.csv"
    model_path.write_text(
        f">>>sql connection:duckdb\nCOPY (SELECT 42 AS value) TO '{output.as_posix()}' (HEADER)\n"
    )
    output = tmp_path / "values.csv"
    with closing(pm.model(model_path, data_root=tmp_path)) as model:
        sql = model.query("sql:0").sql()
        assert not output.exists()
        model.connection.execute(sql)
    assert output.read_text() == "value\n42\n"


def test_format_roundtrip_preserves_execution_and_reports_malformed_source():
    formatted = pm.format(ONE)
    assert pm.format(formatted) == formatted
    assert pm.check(formatted).ok
    assert pm.run(formatted).polars().item() == 42
    with pytest.raises(CompilationError) as caught:
        pm.format("run: ->")
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
    crlf = result.stdout.replace(
        "\n",
        "\r\n",
    ).encode("utf-8")
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


def test_invalid_tool_arguments_leave_model_available():
    with closing(pm.model(ONE)) as model:
        calls = [
            lambda: pm.check(ONE, syntax_only=1),
            lambda: pm.model(ONE).query({}).run().polars(),
            lambda: model.query({}).run().polars(),
            lambda: model.query({}).sql(),
            lambda: to_dict(
                model.inspect(position=SourcePosition(line=0, character=5), url={})
            ),
        ]
        for call in calls:
            with pytest.raises(TypeError):
                call()
            assert model.run().polars().item() == 42


def test_required_givens_leave_source_metadata_available_before_execution():
    source = """##! experimental.givens
given: cutoff :: number
source: numbers is duckdb.sql('SELECT 42 AS value')
run: numbers -> { where: value > $cutoff select: value }
"""
    report = pm.check(source)
    assert report.ok
    assert report.model.model is None
    assert [q.name for q in report.queries] == ["run:0"]
    assert report.model.sources[0].name == "numbers"
    with closing(pm.model(source)) as model:
        inspection = to_dict(model.inspect())
        assert inspection["model"]["model"] is None
        assert inspection["model"]["sources"][0]["name"] == "numbers"
        assert inspection["givens"][0]["name"] == "cutoff"
        assert inspection["givens"][0]["default_text"] is None
        sql = model.query().sql(givens={"cutoff": 10})
        assert model.connection.sql(sql).fetchone() == (42,)


def test_cli_check_reports_database_setup_errors(tmp_path):
    source = tmp_path / "model.malloy"
    source.write_text(ONE)
    database = tmp_path / "invalid.duckdb"
    database.write_text("invalid database contents")
    result = cli("check", source, "--database", database)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("pymalloy:")
