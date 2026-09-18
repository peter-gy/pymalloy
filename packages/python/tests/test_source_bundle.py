import hashlib
import json
import runpy
import shutil

import duckdb
import pytest

import pymalloy as pm
from pymalloy.export import bundle


def test_validated_bundle_relocates_imports_and_data_and_replays_exact_parameters(
    tmp_path, monkeypatch
):
    originals = tmp_path / "original"
    originals.mkdir()
    data = originals / "café orders.parquet"
    with duckdb.connect() as connection:
        connection.execute(
            "COPY (SELECT 1 id, 12 amount UNION ALL SELECT 2, 20) TO ? (FORMAT PARQUET)",
            [str(data)],
        )
    base_url = "https://example.test/models/base?revision=7"
    main_url = "https://example.test/models/reports/report"
    base = pm.draft("// 🌈 source identity\r\n").define(
        orders=pm.table(data).extend(pm.measure(revenue=pm.col("amount").sum()))
    )
    source = pm.ModelSource(
        main_url,
        """// 🌈 preserved attribution
##! experimental.givens
given: cutoff :: number is 0
import {items is orders} from "../base?revision=7"
query: total is items -> {where: amount > $cutoff aggregate: revenue}
""",
        {base_url: base.text},
    )
    report = pm.read_model(source).validate(givens={"cutoff": 15})
    report.require_valid()
    written = bundle(
        report,
        tmp_path / "export",
        files={data: data},
        query="total",
    )
    manifest = json.loads(written.manifest.read_text())
    copied = manifest["files"][0]
    assert (
        copied["sha256"]
        == hashlib.sha256(
            (written.model.parent / copied["path"]).read_bytes()
        ).hexdigest()
    )
    assert "🌈 preserved attribution" in written.model.read_text()
    shutil.rmtree(originals)
    relocated = tmp_path / "relocated"
    written.model.parent.rename(relocated)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    model = pm.model(
        relocated / manifest["model"], data_root=relocated / manifest["data_root"]
    )
    try:
        assert model.query(manifest["query"]).run(givens=manifest["givens"]).rows() == [
            {"revenue": 20}
        ]
        assert set(model.source().imports) == {
            (relocated / record["path"]).as_uri()
            for record in manifest["sources"]
            if record["path"] != "model.malloy"
        }
    finally:
        model.close()
    restored = runpy.run_path(str(relocated / "model.py"))["model"]
    model = restored.compile(data_root=relocated / manifest["data_root"])
    try:
        assert model.query("total").run(givens=manifest["givens"]).rows() == [
            {"revenue": 20}
        ]
    finally:
        model.close()


def test_bundle_distinguishes_inline_root_identity_from_imported_file(tmp_path):
    url = "file:///original/model.malloy"
    original = pm.ModelSource(
        url,
        'import "model.malloy"\nrun: values -> {select: value}\n',
        {url: "source: values is duckdb.sql('SELECT 42 AS value')"},
    )
    artifact = bundle(original, tmp_path / "bundle")
    assert pm.run(artifact.model, data_root=artifact.data_root).rows() == [
        {"value": 42}
    ]


def test_explicit_reader_files_use_native_search_path_without_rewriting_sql(
    tmp_path, monkeypatch
):
    csv = tmp_path / "original.csv"
    csv.write_text("value\n42\n")
    source = pm.ModelSource(
        "memory://project/model.malloy",
        """run: duckdb.sql("SELECT * FROM read_csv('rows.csv')") -> {select: value}""",
    )
    artifact = bundle(source, tmp_path / "bundle", files={"rows.csv": csv})
    assert "read_csv('rows.csv')" in artifact.model.read_text()
    csv.unlink()
    relocated = tmp_path / "relocated"
    artifact.model.parent.rename(relocated)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    replay = relocated / "replay.py"
    assert runpy.run_path(str(replay))["result"].rows() == [{"value": 42}]
    (elsewhere / "rows.csv").write_text("value\n99\n")
    with pytest.raises(ValueError, match="shadowed by the current directory"):
        runpy.run_path(str(replay))


def test_bundle_preflight_leaves_existing_and_failed_destinations_untouched(tmp_path):
    missing = pm.ModelSource("memory://project/model.malloy", 'import "missing.malloy"')
    target = tmp_path / "bundle"
    with pytest.raises(ValueError, match="missing"):
        bundle(missing, target)
    assert not target.exists()
    target.mkdir()
    sentinel = target / "model.malloy"
    sentinel.write_text("owned by caller")
    with pytest.raises(FileExistsError):
        bundle(pm.ModelSource("memory://project/model.malloy", ""), target)
    assert sentinel.read_text() == "owned by caller"
    source = pm.ModelSource("memory://project/model.malloy", "")
    with pytest.raises(ValueError, match="colliding"):
        bundle(
            source, tmp_path / "collision", files={"A.csv": sentinel, "a.csv": sentinel}
        )
    assert not (tmp_path / "collision").exists()


def test_bundle_bytes_are_deterministic_for_equivalent_binding_maps(tmp_path):
    first, second = tmp_path / "first.csv", tmp_path / "second.csv"
    first.write_text("value\n1\n")
    second.write_text("value\n2\n")
    source = pm.ModelSource(
        "memory://bundle/model.malloy",
        'source: first_file is duckdb.table("first.csv")\nsource: second_file is duckdb.table("second.csv")\n',
    )
    left = bundle(
        source, tmp_path / "left", files={"first.csv": first, "second.csv": second}
    )
    right = bundle(
        source, tmp_path / "right", files={"second.csv": second, "first.csv": first}
    )

    def contents(root):
        return {
            str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    assert contents(left.model.parent) == contents(right.model.parent)


def test_explicit_file_binding_keeps_spaces_and_quotes_literal(tmp_path):
    data = tmp_path / "owner's orders.csv"
    data.write_text("value\n42\n")
    candidate = (
        pm.draft()
        .define(orders=pm.table(data))
        .queries(all_orders=pm.ref("orders").pipe(pm.query(pm.select(pm.col("value")))))
    )
    source = pm.ModelSource(candidate.url, candidate.text)
    # A string binding can name the exact quoted table path from native Malloy.
    native_path = "'" + data.as_posix().replace("'", "''") + "'"
    artifact = bundle(source, tmp_path / "bundle", files={native_path: data})
    assert pm.run(artifact.model, data_root=artifact.data_root).rows() == [
        {"value": 42}
    ]


@pytest.mark.parametrize("validated", [False, True])
def test_bundle_replay_preserves_connection_alias(tmp_path, validated):
    data = tmp_path / "orders.csv"
    data.write_text("amount\n42\n")
    candidate = (
        pm.draft()
        .define(orders=pm.table(data, connection="warehouse"))
        .queries(
            summary=pm.ref("orders").pipe(
                pm.query(pm.aggregate(total=pm.col("amount").sum()))
            )
        )
    )
    source = (
        candidate.validate(connection_name="warehouse")
        if validated
        else pm.ModelSource(candidate.url, candidate.text)
    )
    options = {} if validated else {"connection_name": "warehouse"}
    artifact = bundle(
        source, tmp_path / "bundle", files={data: data}, query="summary", **options
    )
    manifest = json.loads(artifact.manifest.read_text())
    assert manifest["connection_name"] == "warehouse"
    assert runpy.run_path(str(artifact.model.parent / "replay.py"))[
        "result"
    ].rows() == [{"total": 42}]
    if validated:
        with pytest.raises(ValueError, match="connection differs from validation"):
            bundle(source, tmp_path / "conflicting", connection_name="other")


def test_model_imports_keep_their_language_independent_of_url_suffix(tmp_path):
    from pymalloy.export import prepare

    imported = "source: values is duckdb.sql('SELECT 42 AS value')"
    root = "import 'base.malloynb'\nrun: values -> {select: value}"
    (tmp_path / "base.malloynb").write_text(imported)
    entry = tmp_path / "model.malloy"
    entry.write_text(root)
    with pm.model(entry) as model:
        source = model.source()
        assert model.run().rows() == [{"value": 42}]
    artifact = bundle(source, tmp_path / "bundle")
    assert pm.run(artifact.model, data_root=artifact.data_root).rows() == [
        {"value": 42}
    ]
    assert prepare(entry).queries[0].name == "run:0"
