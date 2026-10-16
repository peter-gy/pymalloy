import pickle
import runpy
from pathlib import Path

import duckdb
import pytest

import pymalloy as pm


def orders(
    sql="SELECT * FROM (VALUES (1, 10, 'N'), (2, 20, 'S')) t(id, amount, region)",
):
    return (
        pm.sql(sql)
        .doc("One row per order.")
        .primary_key("id")
        .dimension(doubled=(pm.col("amount") * 2).doc("Twice the amount."))
        .measure(revenue=pm.col("amount").sum().doc("Revenue in USD."))
        .view(
            by_region=pm.view()
            .group_by(pm.col("region"))
            .aggregate(pm.col("revenue"))
            .order_by(pm.col("region"))
            .doc("Regional revenue.")
        )
    )


def test_composable_model_joins_parameters_and_reusable_query_clauses():
    grouped = pm.view().group_by(pm.col("region")).aggregate(pm.col("revenue"))
    model = (
        pm.draft("##! experimental.givens\ngiven: minimum :: number is 0\n")
        .sources(
            regions=pm.sql("SELECT 'N' region, 'North' region_name").doc(
                "Region labels."
            ),
            orders=orders(),
        )
        .sources(
            selected=pm.source("orders")
            .join_one(
                "labels",
                pm.source("regions"),
                on=pm.col("region") == pm.col("labels", "region"),
            )
            .where(pm.col("amount") > pm.given("minimum"))
        )
        .queries(
            report=pm.source("selected").pipe(
                pm.view()
                .select(
                    pm.col("id"), pm.col("doubled"), pm.col("labels", "region_name")
                )
                .order_by(pm.col("id"))
            ),
            totals=pm.source("orders").pipe(grouped),
        )
    )
    assert pm.connect().check(model).ok
    runtime = pm.connect().model(model)
    try:
        assert runtime.query("report").preview(limit=1).to_pylist() == [
            {"id": 1, "doubled": 20, "region_name": "North"}
        ]
        assert runtime.query("report").run(givens={"minimum": 10}).to_pylist() == [
            {"id": 2, "doubled": 40, "region_name": None}
        ]
        assert (
            runtime.query(pm.source("orders").pipe(grouped)).run().to_pylist()
            == runtime.query("totals").run().to_pylist()
        )
        assert runtime.query("totals").run().to_pylist() == [
            {"region": "S", "revenue": 20},
            {"region": "N", "revenue": 10},
        ]
    finally:
        runtime.close()


def test_generated_and_parsed_models_share_scoped_edits_and_preserve_annotations():
    original = (
        pm.draft()
        .sources(orders=orders())
        .queries(
            report=pm.source("orders").pipe(pm.view().aggregate(pm.col("revenue")))
        )
    )
    loaded = pm.read_model(original.text)
    for candidate in [original, loaded]:
        revised = candidate.sources(
            orders=candidate["orders"].replace(revenue=pm.col("amount").avg())
        )
        assert revised.text == original.text.replace(
            pm.col("amount").sum().text, pm.col("amount").avg().text
        )
        assert original["orders"]["revenue"].equals(pm.col("amount").sum())
        assert '#" Revenue in USD.' in revised.text
        documented = candidate.sources(
            orders=candidate["orders"].replace(
                revenue=pm.col("amount").avg().doc("Mean amount in USD.")
            )
        )
        assert revised["orders"].names == ("doubled", "revenue", "by_region")
        with pytest.raises(KeyError):
            candidate["orders"].replace(missing=pm.lit(1))
        runtime = pm.connect().model(documented)
        try:
            assert runtime.query("report").run().to_pylist() == [{"revenue": 15.0}]
            source = next(
                s for s in runtime.inspect().model.sources if s.name == "orders"
            )
            measure = next(f for f in source.schema.fields if f.name == "revenue")
            assert [note.value.strip() for note in measure.annotations] == [
                '#" Mean amount in USD.'
            ]
        finally:
            runtime.close()


def test_nested_queries_keep_their_own_field_scope_after_import():
    view = (
        pm.view()
        .aggregate(x=pm.count())
        .nest(details=pm.view().aggregate(x=pm.count()))
    )
    original = pm.draft().sources(orders=orders().view(summary=view))
    for candidate in [original, pm.read_model(original.text)]:
        summary = candidate["orders"]["summary"]
        assert summary.names == ("x", "details")
        assert summary["details"].names == ("x",)
        edited = summary.replace(details=summary["details"].replace(x=pm.count() + 1))
        result = pm.connect().model(
            candidate.sources(orders=candidate["orders"].replace(summary=edited))
        )
        try:
            assert result.query("orders.summary").run().to_pylist() == [
                {"x": 2, "details": {"x": 3}}
            ]
        finally:
            result.close()
    anonymous = pm.read_model(
        "run: duckdb.sql('SELECT 42 AS value') -> {aggregate: n is count()}"
    )
    assert anonymous.names == ()
    assert anonymous.sources(n=pm.sql("SELECT 1 AS value")).names == ("n",)


def test_python_roundtrip_retains_semantics_unicode_imports_and_parameters(
    tmp_path,
):
    (tmp_path / "base.malloy").write_text(
        "source: base is duckdb.sql('SELECT 42 AS value')"
    )
    text = "\r\n".join(  # noqa: FLY002 - Exercise exact CRLF source preservation.
        [
            "// 😀 source with Python-looking content: __import__('os')",
            "##! experimental.givens",
            "##! experimental.parameters",
            "given: threshold :: number is 2",
            "import {base} from 'base.malloy'",
            '#" Authored description',
            "source: `a\\`b`(p :: number is 1) is # note=kept",
            'duckdb.sql("SELECT 42 AS value") extend { dimension: `path\\\\name` is value }, other is base;',
            "query: answer is other -> {select: value}",
            "run: answer",
            "// keep final trivia",
            "",
        ]
    )
    path = tmp_path / "source.malloy"
    path.write_bytes(text.encode())
    original = pm.read_model(path)
    assert original.text == text
    assert original.names == ("a`b", "other", "answer")
    generated = tmp_path / "generated.py"
    generated.write_text(original.to_python(name="restored"), encoding="utf-8")
    restored = runpy.run_path(str(generated))["restored"]
    assert restored["a`b"]["path\\name"].equals(pm.col("value"))
    for trivia in [
        "// 😀 source with Python-looking content: __import__('os')\r\n",
        "given: threshold :: number is 2\r\n",
        "import {base} from 'base.malloy'\r\n",
        '#" Authored description\r\n',
        "# note=kept\r\n",
        "// keep final trivia\r\n",
    ]:
        assert trivia in restored.text
    sql = []
    for candidate in [original, restored]:
        model = pm.connect().model(candidate)
        try:
            sql.append(model.query("answer").sql())
            assert model.query("answer").run().to_pylist() == [{"value": 42}]
        finally:
            model.close()
    assert sql[0] == sql[1]
    edited = restored.sources(
        **{"a`b": restored["a`b"].replace(**{"path\\name": pm.col("value") * 2})}
    )
    model = pm.connect().model(edited)
    try:
        assert model.query(
            malloy="run: `a\\`b` -> { select: `path\\\\name` }"
        ).run().to_pylist() == [{"path\\name": 84}]
    finally:
        model.close()
    assert (
        original.save(tmp_path / "unchanged.malloy").read_bytes() == path.read_bytes()
    )


def test_validation_counterexamples_refuse_writes_of_failed_models(tmp_path):
    candidate = pm.draft().sources(orders=orders())
    checks = {
        "unique": pm.source("orders").pipe(
            pm.view()
            .group_by(pm.col("id"))
            .aggregate(n=pm.count())
            .having(pm.col("n") > 1)
        ),
        "nonnegative": pm.source("orders").pipe(
            pm.view().where(pm.col("amount") < 0).select(pm.col("id"))
        ),
    }
    report = pm.connect().validate(candidate, checks)
    assert report.ok and report.require_valid(warnings_as_errors=True) is report
    saved = report.save(tmp_path / "orders.malloy")
    assert pm.connect().check(pm.read_model(saved)).ok
    broken = candidate.sources(
        orders=orders(
            "SELECT * FROM (VALUES (1,10,'N'), (1,-20,'S')) t(id,amount,region)"
        )
    )
    failed = pm.connect().validate(broken, checks)
    assert not failed.ok
    assert [c.status for c in failed.checks] == ["failed", "failed"]
    assert failed.checks[0].result.to_pylist() == [{"id": 1, "n": 2}]
    assert failed.checks[1].result.to_pylist() == [{"id": 1}]
    with pytest.raises(pm.errors.ValidationError, match="validation failed"):
        failed.save(saved, overwrite=True)
    assert saved.read_text() == candidate.text


def test_compiler_and_opt_in_documentation_findings_share_one_report(tmp_path):
    from pymalloy.validation import DocumentationPolicy

    candidate = pm.draft().sources(
        orders=pm.sql("SELECT '#\" not documentation' note, 1 amount")
        .measure(revenue=pm.col("amount").sum())
        .view(summary=pm.view().aggregate(pm.col("revenue")))
    )
    assert pm.connect().check(candidate).diagnostics == ()
    assert pm.connect().validate(candidate).diagnostics == ()
    policy = DocumentationPolicy()
    report = pm.connect().check(candidate, documentation=policy)
    assert report.ok
    assert {d.code for d in report.diagnostics} == {
        "missing-source-doc",
        "missing-measure-doc",
        "missing-view-doc",
    }
    validated = pm.connect().validate(candidate, documentation=policy)
    assert validated.ok
    with pytest.raises(pm.errors.ValidationError, match="Document"):
        validated.save(tmp_path / "model.malloy", warnings_as_errors=True)
    assert not (tmp_path / "model.malloy").exists()
    invalid = candidate.sources(
        orders=candidate["orders"].replace(revenue=pm.col("missing").sum())
    )
    assert not pm.connect().check(invalid).ok
    failed = pm.connect().validate(
        invalid, {"probe": pm.source("orders").pipe(pm.view().select(pm.col("id")))}
    )
    assert not failed.ok and failed.error
    assert failed.checks[0].status == "skipped"
    with pytest.raises(pm.errors.CompilationError):
        pm.read_model("source: broken is {")


def test_import_snapshots_preserve_crlf_and_reject_changed_files(tmp_path):
    dependency = tmp_path / "base.malloy"
    dependency.write_bytes(
        pm.draft().sources(orders=orders()).text.replace("\n", "\r\n").encode()
    )
    path = tmp_path / "domain.malloy"
    path.write_bytes(b'import "base.malloy"\r\n')
    original = pm.read_model(path)
    candidate = original.sources(expanded=pm.source("orders").measure(rows=pm.count()))
    assert "+source:" in candidate.diff()
    report = pm.connect().validate(
        candidate,
        {
            "count": pm.source("expanded").pipe(
                pm.view().aggregate(pm.col("rows")).having(pm.col("rows") != 2)
            )
        },
    )
    assert report.ok
    assert report.draft.imports[dependency.as_uri()] == dependency.read_bytes().decode()
    saved = report.save(tmp_path / "copied.malloy")
    assert pm.connect().check(saved).ok
    snapshot = pm.ModelSource(candidate.url, candidate.text, report.draft.imports)
    assert (
        pm.connect()
        .validate(pm.read_model(snapshot))
        .save(tmp_path / "snapshot.malloy")
        .is_file()
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    with pytest.raises(ValueError, match="beside"):
        report.save(elsewhere / "model.malloy")
    dependency.write_text("source: broken is missing")
    assert not pm.connect().check(candidate).ok
    assert pm.connect().check(report.draft).ok
    with pytest.raises(ValueError, match="Imported model changed"):
        report.save()
    generated = tmp_path / "snapshot.py"
    generated.write_text(report.draft.to_python())
    scope = runpy.run_path(str(generated))
    assert scope["model"].imports == report.draft.imports
    assert pm.connect().check(scope["model"]).ok
    path.write_text("// changed externally\n")
    with pytest.raises(ValueError, match="changed on disk"):
        candidate.save()


def test_loaded_edits_keep_source_file_ownership(tmp_path):
    path = pm.draft().sources(orders=orders()).save(tmp_path / "orders.malloy")
    loaded = pm.read_model(path)
    updated = loaded.sources(
        orders=loaded["orders"].replace(revenue=pm.col("doubled").sum())
    )
    assert pm.connect().check(updated.format()).ok
    updated.save()
    assert path.read_text() == updated.text
    with pytest.raises(ValueError, match="changed on disk"):
        loaded.save()
    assert loaded.text != updated.text


def test_validation_bounds_counterexamples_and_preserves_borrowed_connections():
    with duckdb.connect() as connection:
        connection.execute("CREATE TABLE numbers AS SELECT i FROM range(1000) t(i)")
        connection.execute("BEGIN")
        candidate = pm.draft().sources(numbers=pm.table("numbers"))
        report = pm.connect(database=connection).validate(
            candidate,
            {
                "small": pm.source("numbers").pipe(
                    pm.view()
                    .where(pm.col("i") > 10)
                    .select(pm.col("i"))
                    .order_by(pm.col("i"))
                ),
                "invalid": pm.source("missing"),
                "engine": pm.sql("SELECT error('bad value') value").pipe(
                    pm.view().select(pm.col("value"))
                ),
            },
        )
        assert not report.ok
        assert report.checks[0].result.to_pylist() == [{"i": 11}]
        assert report.checks[1].status == "error" and report.checks[1].diagnostics
        assert report.checks[2].status == "error"
        connection.execute("ROLLBACK")
        assert connection.execute("SELECT count(*) FROM numbers").fetchone() == (1000,)


def test_preview_uses_native_limits_comments_and_statement_classification(tmp_path):
    output = tmp_path / "must-not-exist.csv"
    model = pm.connect().model(
        f">>>sql connection:duckdb\nCOPY (SELECT 1) TO '{output}' (FORMAT CSV)\n",
        url="memory://test/copy.malloynb",
    )
    try:
        with pytest.raises(ValueError, match="SELECT"):
            model.query("sql:0").preview()
        assert not output.exists()
    finally:
        model.close()
    model = pm.connect().model(
        ">>>sql connection:duckdb\nSELECT '; -- value' AS value FROM range(100000); -- comment\n",
        url="memory://test/comments.malloynb",
    )
    try:
        assert (
            model.query("sql:0").preview(limit=3).to_pylist()
            == [{"value": "; -- value"}] * 3
        )
        with pytest.raises(ValueError, match="limit"):
            model.query("sql:0").preview(limit=True)
    finally:
        model.close()


def test_file_paths_names_and_empty_expressions_are_unambiguous(tmp_path):
    file = tmp_path / "orders' data.csv"
    file.write_text("id,amount\n1,42\n")
    model = (
        pm.draft()
        .sources(**{"order facts": pm.table(Path(file.name))})
        .queries(
            summary=pm.source("order facts").pipe(
                pm.view().aggregate(total=pm.col("amount").sum())
            )
        )
    )
    runtime = pm.connect(data_root=tmp_path).model(model)
    try:
        assert runtime.query("summary").preview().to_pylist() == [{"total": 42}]
    finally:
        runtime.close()
    with pytest.raises(ValueError, match="Limit"):
        pm.view().limit(True)
    for suffix in ["malloynb", "malloysql"]:
        with pytest.raises(ValueError, match=".malloy document"):
            pm.read_model("", url=f"memory://test/model.{suffix}")
    with pytest.raises(ValueError, match="ambiguous"):
        pm.read_model("source: x is y, x is z")["x"]


def test_parsed_document_preserves_the_named_editing_scope():
    original = pm.draft().sources(orders=pm.sql("SELECT 1 amount"))
    nested = pm.read_model(original.text)
    updated = nested.sources(orders=pm.sql("SELECT 2 amount"))
    assert updated.names == ("orders",)
    assert updated["orders"].text == pm.sql("SELECT 2 amount").text
    assert original["orders"].text == pm.sql("SELECT 1 amount").text
    assert updated.text == pm.draft().sources(orders=pm.sql("SELECT 2 amount")).text


def test_batch_edits_preserve_warmed_text_and_scopes():
    original = pm.draft().sources(
        first=pm.sql("SELECT 1 amount"), second=pm.sql("SELECT 2 amount")
    )
    original_text = original.text
    assert original["second"].text == pm.sql("SELECT 2 amount").text
    restored = pickle.loads(pickle.dumps(original))
    assert restored.text == original_text
    assert restored["second"].text == original["second"].text
    updated = original.sources(
        third=pm.sql("SELECT 3 amount"), second=pm.sql("SELECT 42 amount")
    )
    assert updated.names == ("first", "second", "third")
    assert original.text == original_text
    assert "SELECT 42 amount" in updated.text
    model = pm.connect().model(
        updated.queries(
            result=pm.source("second").pipe(pm.view().select(pm.col("amount")))
        )
    )
    try:
        assert model.query("result").run().to_pylist() == [{"amount": 42}]
    finally:
        model.close()
    ambiguous = pm.read_model(original.text + updated.text)
    with pytest.raises(ValueError, match="ambiguous"):
        ambiguous["second"]


def test_native_descriptions_structural_routes_and_explicit_documentation_policy():
    from pymalloy.validation import DocumentationPolicy

    candidate = pm.read_model("""
#" Order lines, one row per id.
source: orders is duckdb.sql('SELECT 1 id, 12 amount') extend {
  measure:
    #" Revenue in USD.
    #[research] unit=USD
    revenue is amount.sum()
}
""")
    report = pm.connect().check(candidate)
    assert not report.diagnostics
    notes = next(
        item
        for item in report.model.annotations
        if list(item.path) == ["orders", "revenue"]
    )
    assert [(note.route, note.content.strip()) for note in notes.annotations] == [
        ('"', "Revenue in USD."),
        ("research", "unit=USD"),
    ]
    assert (
        pm.connect()
        .check(
            candidate,
            documentation=DocumentationPolicy(routes=("research",), kinds=("measure",)),
        )
        .ok
    )
    strict = DocumentationPolicy(routes=("business",), severity="error")
    assert not pm.connect().check(candidate, documentation=strict).ok
    assert not pm.connect().validate(candidate, documentation=strict).ok
    revised = candidate.sources(
        orders=candidate["orders"].replace(
            revenue=pm.col("amount").avg().doc("Mean line amount in USD.")
        )
    )
    report = pm.connect().check(revised)
    assert not report.diagnostics
    notes = next(
        item
        for item in report.model.annotations
        if list(item.path) == ["orders", "revenue"]
    )
    assert [(note.route, note.content.strip()) for note in notes.annotations] == [
        ('"', "Mean line amount in USD."),
        ("research", "unit=USD"),
    ]


def test_python_emission_uses_composable_constructors_and_keeps_opaque_trivia(tmp_path):
    reusable = pm.view().group_by(pm.col("region")).aggregate(pm.col("revenue"))
    candidate = (
        pm.draft()
        .sources(orders=orders())
        .sources(north=pm.source("orders").where(pm.col("region") == "N"))
        .queries(summary=pm.source("north").pipe(reusable))
    )
    generated = candidate.to_python()
    assert ".sources(" in generated and ".queries(" in generated
    assert ".measure(" in generated and "pm.view(" in generated
    draft = pm.read_model("// authored trivia\r\n" + candidate.text)
    emitted = tmp_path / "model.py"
    emitted.write_text(draft.to_python())
    restored = runpy.run_path(str(emitted))["model"]
    assert "// authored trivia" in restored.text
    restored = restored.sources(
        north=pm.source("orders").where(pm.col("region") == "S")
    )
    with pm.connect().model(restored) as runtime:
        assert runtime.query("summary").run().to_pylist() == [
            {"region": "S", "revenue": 20}
        ]


def test_python_emission_decodes_strings_with_native_malloy_semantics(tmp_path):
    source = r"""source: values is duckdb.sql("SELECT '\u0041' AS value")
query: result is values -> {select: value}
"""
    candidate = pm.read_model(source)
    path = tmp_path / "literal.py"
    path.write_text(candidate.to_python())
    restored = runpy.run_path(str(path))["model"]
    assert candidate.text == source
    with (
        pm.connect().model(candidate) as original,
        pm.connect().model(restored) as rebuilt,
    ):
        assert original.query("result").sql() == rebuilt.query("result").sql()
        assert (
            original.query("result").run().to_pylist()
            == rebuilt.query("result").run().to_pylist()
            == [{"value": "A"}]
        )


def test_handwritten_models_emit_editable_constructors_independent_of_layout(tmp_path):
    source = """source: sales is duckdb.sql('SELECT 3 amount, 2 n') extend {
      dimension: doubled is amount * 2
      measure: revenue is amount.sum()
      view: totals is {
        aggregate: revenue
        order_by: revenue desc
        limit: 1
        nest: detail is {select: doubled}
      }
    }
    query: result is sales -> totals
    """
    candidate = pm.read_model(source)
    generated = candidate.to_python()
    assert ".dimension(" in generated and ".measure(" in generated
    assert "pm.view(" in generated and ".queries(" in generated
    assert ".order_by(" in generated and ".desc()" in generated
    assert ".nest(" in generated and ".limit(1)" in generated
    path = tmp_path / "model.py"
    path.write_text(generated)
    restored = runpy.run_path(str(path))["model"]
    assert candidate.text == source
    with (
        pm.connect().model(candidate) as original,
        pm.connect().model(restored) as rebuilt,
    ):
        left = original.query("result").run()
        right = rebuilt.query("result").run()
        assert left.columns == right.columns
        assert left.to_pylist() == right.to_pylist()
    revised = restored.sources(
        sales=restored["sales"].replace(revenue=pm.col("amount").sum() * 2)
    )
    with pm.connect().model(revised) as model:
        assert model.query("result").run().to_pylist() == [
            {"revenue": 6, "detail": [{"doubled": 6}]}
        ]


def test_annotations_preserve_other_routes_when_replaced_and_reconstructed(tmp_path):
    candidate = (
        pm.draft()
        .sources(
            sales=pm.sql("SELECT 2 amount")
            .measure(
                revenue=pm.col("amount")
                .sum()
                .doc("Revenue")
                .annotate("unit=USD", route="research")
                .annotate("currency=USD")
            )
            .view(totals=pm.view().aggregate(pm.col("revenue")).annotate("bar_chart"))
        )
        .queries(result=pm.source("sales").pipe("totals"))
    )
    loaded = pm.read_model(candidate.text)
    revised = loaded.sources(
        sales=loaded["sales"].replace(
            revenue=pm.col("amount").sum().annotate("unit=EUR", route="research")
        )
    )
    path = tmp_path / "model.py"
    path.write_text(revised.to_python())
    restored = runpy.run_path(str(path))["model"]
    with (
        pm.connect().model(revised) as original,
        pm.connect().model(restored) as rebuilt,
    ):
        for model in (original, rebuilt):
            revenue = next(
                item
                for item in model.inspect().model.annotations
                if list(item.path) == ["sales", "revenue"]
            )
            assert sorted(
                (note.route, note.content.strip()) for note in revenue.annotations
            ) == [("", "currency=USD"), ('"', "Revenue"), ("research", "unit=EUR")]
        assert (
            original.query("result").run().to_pylist()
            == rebuilt.query("result").run().to_pylist()
        )


def test_python_projection_retains_unsupported_clause_operands(tmp_path):
    source = """source: data is duckdb.sql('SELECT 1 a, 2 b') extend {
      view: detailed is {select: *, extra is a + b}
    }
    query: result is data -> detailed
    """
    candidate = pm.read_model(source)
    path = tmp_path / "model.py"
    path.write_text(candidate.to_python())
    restored = runpy.run_path(str(path))["model"]
    with (
        pm.connect().model(candidate) as original,
        pm.connect().model(restored) as rebuilt,
    ):
        assert (
            original.query("result").run().to_pylist()
            == rebuilt.query("result").run().to_pylist()
            == [{"a": 1, "b": 2, "extra": 3}]
        )


def test_python_reconstruction_retains_a_captured_inputs_connection(tmp_path):
    import pyarrow as pa

    frame = pa.table({"value": [1, 2]})
    candidate = (
        pm.draft()
        .sources(values=pm.data(frame, name="values", connection="warehouse"))
        .queries(
            result=pm.source("values").pipe(
                pm.view().aggregate(total=pm.col("value").sum())
            )
        )
    )
    path = tmp_path / "model.py"
    path.write_text(candidate.to_python(inputs={"values": "frame"}))
    restored = runpy.run_path(str(path), init_globals={"frame": frame})["model"]
    with pm.connect(name="warehouse").model(restored) as model:
        assert model.query("result").run().to_pylist() == [{"total": 3}]


def test_constructor_text_is_readable_without_reformatting_raw_literals():
    inline = 'duckdb.sql("""SELECT \'first\nsecond\' AS label""")'
    candidate = (
        pm.draft()
        .sources(
            orders=pm.sql("SELECT 1 AS value")
            .dimension(day=pm.col("value"), days=pm.col("value"))
            .join_one("labels", pm.Source.raw(inline), on=pm.lit(True))
            .view(
                details=pm.view().select(
                    pm.col("day"), pm.col("days"), pm.col("labels", "label")
                )
            )
        )
        .queries(result=pm.source("orders").pipe("details"))
    )
    assert candidate.text.startswith("source: orders is duckdb.sql(")
    assert "  dimension:\n    `day` is value\n    `days` is value\n" in candidate.text
    assert (
        "  view: details is {\n    select: `day`, `days`, labels.label\n  }"
        in candidate.text
    )
    assert inline in candidate.text
    assert pm.read_model(candidate.text).text == candidate.text
    assert pm.source("orders").pipe().text == "orders"
    with pm.connect().model(candidate) as model:
        assert model.query("result").run().to_pylist() == [
            {"day": 1, "days": 1, "label": "first\nsecond"}
        ]


def test_generated_blocks_leave_raw_block_annotations_at_their_authored_columns():
    raw = "#|(research)\n  body\n|#\nselect: amount"
    candidate = (
        pm.draft()
        .sources(
            values=pm.sql("SELECT 1 amount").view(
                detail=pm.View.raw(
                    "{\n",
                    pm.Source.raw(raw).doc("Details").annotate("currency=USD"),
                    "\n}",
                )
            )
        )
        .queries(result=pm.source("values").pipe("detail"))
    )
    assert "\n" + raw + "\n" in candidate.text
    with pm.connect().model(candidate) as model:
        assert model.query("result").run().to_pylist() == [{"amount": 1}]
