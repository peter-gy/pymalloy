import pickle
import runpy
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

import pymalloy as pm


def orders(
    sql="SELECT * FROM (VALUES (1, 10, 'N'), (2, 20, 'S')) t(id, amount, region)",
):
    return (
        pm.sql(sql)
        .doc("One row per order.")
        .extend(
            pm.primary_key("id"),
            pm.dimension(doubled=(pm.col("amount") * 2).doc("Twice the amount.")),
            pm.measure(revenue=pm.col("amount").sum().doc("Revenue in USD.")),
            pm.view(
                by_region=pm.query(
                    pm.group_by(pm.col("region")),
                    pm.aggregate(pm.col("revenue")),
                    pm.order_by(pm.col("region")),
                ).doc("Regional revenue.")
            ),
        )
    )


def test_composable_model_joins_parameters_and_reusable_query_clauses():
    grouped = pm.query(pm.group_by(pm.col("region")), pm.aggregate(pm.col("revenue")))
    model = (
        pm.draft("##! experimental.givens\ngiven: minimum :: number is 0\n")
        .define(
            regions=pm.sql("SELECT 'N' region, 'North' region_name").doc(
                "Region labels."
            ),
            orders=orders(),
        )
        .define(
            selected=pm.ref("orders").extend(
                pm.join(
                    "labels",
                    pm.ref("regions"),
                    on=pm.col("region") == pm.col("labels", "region"),
                    kind="one",
                ),
                pm.where(pm.col("amount") > pm.given("minimum")),
            )
        )
        .queries(
            report=pm.ref("selected").pipe(
                pm.query(
                    pm.select(
                        pm.col("id"), pm.col("doubled"), pm.col("labels", "region_name")
                    ),
                    pm.order_by(pm.col("id")),
                )
            ),
            totals=pm.ref("orders").pipe(grouped),
        )
    )
    assert model.check().ok
    runtime = model.compile()
    try:
        assert runtime.query("report").preview(limit=1).rows() == [
            {"id": 1, "doubled": 20, "region_name": "North"}
        ]
        assert runtime.query("report").run(givens={"minimum": 10}).rows() == [
            {"id": 2, "doubled": 40, "region_name": None}
        ]
        assert (
            runtime.query(pm.ref("orders").pipe(grouped)).run().rows()
            == runtime.query("totals").run().rows()
        )
        assert runtime.query("totals").run().rows() == [
            {"region": "S", "revenue": 20},
            {"region": "N", "revenue": 10},
        ]
    finally:
        runtime.close()


def test_generated_and_parsed_models_share_scoped_edits_and_preserve_annotations():
    original = (
        pm.draft()
        .define(orders=orders())
        .queries(
            report=pm.ref("orders").pipe(pm.query(pm.aggregate(pm.col("revenue"))))
        )
    )
    loaded = pm.read_model(original.text)
    for candidate in [original, loaded]:
        revised = candidate.define(
            orders=candidate["orders"].replace(revenue=pm.col("amount").avg())
        )
        assert revised.text == original.text.replace(
            pm.col("amount").sum().text, pm.col("amount").avg().text
        )
        assert original["orders"]["revenue"].equals(pm.col("amount").sum())
        assert '#" Revenue in USD.' in revised.text
        documented = candidate.define(
            orders=candidate["orders"].replace(
                revenue=pm.col("amount").avg().doc("Mean amount in USD.")
            )
        )
        assert revised["orders"].names == ("doubled", "revenue", "by_region")
        with pytest.raises(KeyError):
            candidate["orders"].replace(missing=pm.lit(1))
        runtime = documented.compile()
        try:
            assert runtime.query("report").run().rows() == [{"revenue": 15.0}]
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
    view = pm.query(
        pm.aggregate(x=pm.count()),
        pm.nest(details=pm.query(pm.aggregate(x=pm.count()))),
    )
    original = pm.draft().define(orders=orders().extend(pm.view(summary=view)))
    for candidate in [original, pm.read_model(original.text)]:
        summary = candidate["orders"]["summary"]
        assert summary.names == ("x", "details")
        assert summary["details"].names == ("x",)
        edited = summary.replace(details=summary["details"].replace(x=pm.count() + 1))
        result = candidate.define(
            orders=candidate["orders"].replace(summary=edited)
        ).compile()
        try:
            assert result.query("orders.summary").run().rows() == [
                {"x": 2, "details": {"x": 3}}
            ]
        finally:
            result.close()
    anonymous = pm.read_model(
        "run: duckdb.sql('SELECT 42 AS value') -> {aggregate: n is count()}"
    )
    assert anonymous.names == ()
    assert anonymous.define(n=pm.sql("SELECT 1 AS value")).names == ("n",)


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
    generated.write_text(original.to_python(name="restored"))
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
        model = candidate.compile()
        try:
            sql.append(model.query("answer").sql())
            assert model.query("answer").run().rows() == [{"value": 42}]
        finally:
            model.close()
    assert sql[0] == sql[1]
    edited = restored.define(
        **{"a`b": restored["a`b"].replace(**{"path\\name": pm.col("value") * 2})}
    )
    model = edited.compile()
    try:
        assert model.query(
            malloy="run: `a\\`b` -> { select: `path\\\\name` }"
        ).run().rows() == [{"path\\name": 84}]
    finally:
        model.close()
    assert (
        original.save(tmp_path / "unchanged.malloy").read_bytes() == path.read_bytes()
    )


def test_validation_counterexamples_refuse_writes_of_failed_models(tmp_path):
    candidate = pm.draft().define(orders=orders())
    checks = {
        "unique": pm.ref("orders").pipe(
            pm.query(
                pm.group_by(pm.col("id")),
                pm.aggregate(n=pm.count()),
                pm.having(pm.col("n") > 1),
            )
        ),
        "nonnegative": pm.ref("orders").pipe(
            pm.query(pm.where(pm.col("amount") < 0), pm.select(pm.col("id")))
        ),
    }
    report = candidate.validate(checks)
    assert report.ok and report.require_valid(warnings_as_errors=True) is report
    saved = report.save(tmp_path / "orders.malloy")
    assert pm.read_model(saved).check().ok
    broken = candidate.define(
        orders=orders(
            "SELECT * FROM (VALUES (1,10,'N'), (1,-20,'S')) t(id,amount,region)"
        )
    )
    failed = broken.validate(checks)
    assert not failed.ok
    assert [c.status for c in failed.checks] == ["failed", "failed"]
    assert failed.checks[0].result.rows() == [{"id": 1, "n": 2}]
    assert failed.checks[1].result.rows() == [{"id": 1}]
    with pytest.raises(ValueError, match="validation failed"):
        failed.save(saved, overwrite=True)
    assert saved.read_text() == candidate.text


def test_compiler_and_opt_in_documentation_findings_share_one_report(tmp_path):
    from pymalloy.validation import DocumentationPolicy

    candidate = pm.draft().define(
        orders=pm.sql("SELECT '#\" not documentation' note, 1 amount").extend(
            pm.measure(revenue=pm.col("amount").sum()),
            pm.view(summary=pm.query(pm.aggregate(pm.col("revenue")))),
        )
    )
    assert candidate.check().diagnostics == ()
    assert candidate.validate().diagnostics == ()
    policy = DocumentationPolicy()
    report = candidate.check(documentation=policy)
    assert report.ok
    assert {d.code for d in report.diagnostics} == {
        "missing-source-doc",
        "missing-measure-doc",
        "missing-view-doc",
    }
    validated = candidate.validate(documentation=policy)
    assert validated.ok
    with pytest.raises(ValueError, match="Document"):
        validated.save(tmp_path / "model.malloy", warnings_as_errors=True)
    assert not (tmp_path / "model.malloy").exists()
    invalid = candidate.define(
        orders=candidate["orders"].replace(revenue=pm.col("missing").sum())
    )
    assert not invalid.check().ok
    failed = invalid.validate(
        {"probe": pm.ref("orders").pipe(pm.query(pm.select(pm.col("id"))))}
    )
    assert not failed.ok and failed.error
    assert failed.checks[0].status == "skipped"
    with pytest.raises(pm.CompilationError):
        pm.read_model("source: broken is {")


def test_import_snapshots_preserve_crlf_and_reject_changed_files(tmp_path):
    dependency = tmp_path / "base.malloy"
    dependency.write_bytes(
        pm.draft().define(orders=orders()).text.replace("\n", "\r\n").encode()
    )
    path = tmp_path / "domain.malloy"
    path.write_bytes(b'import "base.malloy"\r\n')
    original = pm.read_model(path)
    candidate = original.define(
        expanded=pm.ref("orders").extend(pm.measure(rows=pm.count()))
    )
    assert "+source:" in candidate.diff()
    report = candidate.validate(
        {
            "count": pm.ref("expanded").pipe(
                pm.query(pm.aggregate(pm.col("rows")), pm.having(pm.col("rows") != 2))
            )
        }
    )
    assert report.ok
    assert report.draft.imports[dependency.as_uri()] == dependency.read_bytes().decode()
    saved = report.save(tmp_path / "copied.malloy")
    assert pm.check(saved).ok
    snapshot = pm.ModelSource(candidate.url, candidate.text, report.draft.imports)
    assert (
        pm.read_model(snapshot).validate().save(tmp_path / "snapshot.malloy").is_file()
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    with pytest.raises(ValueError, match="beside"):
        report.save(elsewhere / "model.malloy")
    dependency.write_text("source: broken is missing")
    assert not candidate.check().ok
    assert report.draft.check().ok
    with pytest.raises(ValueError, match="Imported model changed"):
        report.save()
    generated = tmp_path / "snapshot.py"
    generated.write_text(report.draft.to_python())
    scope = runpy.run_path(str(generated))
    assert scope["model"].imports == report.draft.imports
    assert scope["model"].check().ok
    path.write_text("// changed externally\n")
    with pytest.raises(ValueError, match="changed on disk"):
        candidate.save()


def test_loaded_edits_keep_source_file_ownership(tmp_path):
    path = pm.draft().define(orders=orders()).save(tmp_path / "orders.malloy")
    loaded = pm.read_model(path)
    updated = loaded.define(
        orders=loaded["orders"].replace(revenue=pm.col("doubled").sum())
    )
    assert updated.format().check().ok
    updated.save()
    assert path.read_text() == updated.text
    with pytest.raises(ValueError, match="changed on disk"):
        loaded.save()
    assert loaded.text != updated.text


def test_validation_bounds_counterexamples_and_preserves_borrowed_connections():
    with duckdb.connect() as connection:
        connection.execute("CREATE TABLE numbers AS SELECT i FROM range(1000) t(i)")
        connection.execute("BEGIN")
        candidate = pm.draft().define(numbers=pm.table("numbers"))
        report = candidate.validate(
            {
                "small": pm.ref("numbers").pipe(
                    pm.query(
                        pm.where(pm.col("i") > 10),
                        pm.select(pm.col("i")),
                        pm.order_by(pm.col("i")),
                    )
                ),
                "invalid": pm.ref("missing"),
                "engine": pm.sql("SELECT error('bad value') value").pipe(
                    pm.query(pm.select(pm.col("value")))
                ),
            },
            connection=connection,
        )
        assert not report.ok
        assert report.checks[0].result.rows() == [{"i": 11}]
        assert report.checks[1].status == "error" and report.checks[1].diagnostics
        assert report.checks[2].status == "error"
        connection.execute("ROLLBACK")
        assert connection.execute("SELECT count(*) FROM numbers").fetchone() == (1000,)


def test_preview_uses_native_limits_comments_and_statement_classification(tmp_path):
    output = tmp_path / "must-not-exist.csv"
    model = pm.model(
        f">>>sql connection:duckdb\nCOPY (SELECT 1) TO '{output}' (FORMAT CSV)\n",
        url="memory://test/copy.malloynb",
    )
    try:
        with pytest.raises(ValueError, match="SELECT"):
            model.query("sql:0").preview()
        assert not output.exists()
    finally:
        model.close()
    model = pm.model(
        ">>>sql connection:duckdb\nSELECT '; -- value' AS value FROM range(100000); -- comment\n",
        url="memory://test/comments.malloynb",
    )
    try:
        assert (
            model.query("sql:0").preview(limit=3).rows()
            == [{"value": "; -- value"}] * 3
        )
        with pytest.raises(ValueError, match="limit"):
            model.query("sql:0").preview(limit=True)
    finally:
        model.close()


def test_validation_uses_one_budget_and_releases_its_model(monkeypatch):
    from pymalloy._server import validation

    candidate = pm.draft().define(orders=orders())
    elapsed = 0
    preview = pm.Query.preview
    create = pm.Draft.compile
    opened = []

    def finish_first(self, **options):
        nonlocal elapsed
        result = preview(self, **options)
        elapsed = 121
        return result

    def load(*args, **options):
        model = create(*args, **options)
        opened.append(model)
        return model

    monkeypatch.setattr(validation, "time", SimpleNamespace(monotonic=lambda: elapsed))
    monkeypatch.setattr(pm.Query, "preview", finish_first)
    monkeypatch.setattr(pm.Draft, "compile", load)
    with duckdb.connect() as connection:
        with pytest.raises(TimeoutError, match="deadline"):
            candidate.validate(
                {
                    "first": pm.ref("orders").pipe(
                        pm.query(pm.where(pm.lit(False)), pm.select(pm.col("id")))
                    ),
                    "after": pm.ref("orders").pipe(
                        pm.query(pm.where(pm.lit(False)), pm.select(pm.col("id")))
                    ),
                },
                connection=connection,
                timeout=120,
            )
        assert opened and all(m.closed for m in opened)
        assert connection.execute("SELECT 42").fetchone() == (42,)


def test_file_paths_names_and_empty_expressions_are_unambiguous(tmp_path):
    file = tmp_path / "orders' data.csv"
    file.write_text("id,amount\n1,42\n")
    model = (
        pm.draft()
        .define(**{"order facts": pm.table(Path(file.name))})
        .queries(
            summary=pm.ref("order facts").pipe(
                pm.query(pm.aggregate(total=pm.col("amount").sum()))
            )
        )
    )
    runtime = model.compile(data_root=tmp_path)
    try:
        assert runtime.query("summary").preview().rows() == [{"total": 42}]
    finally:
        runtime.close()
    with pytest.raises(ValueError, match="Limit"):
        pm.limit(True)
    for suffix in ["malloynb", "malloysql"]:
        with pytest.raises(ValueError, match=".malloy document"):
            pm.read_model("", url=f"memory://test/model.{suffix}")
    with pytest.raises(ValueError, match="ambiguous"):
        pm.read_model("source: x is y, x is z")["x"]


def test_composed_document_fragments_share_the_named_editing_scope():
    original = pm.draft().define(orders=pm.sql("SELECT 1 amount"))
    nested = pm.draft(original.syntax)
    updated = nested.define(orders=pm.sql("SELECT 2 amount"))
    assert updated.names == ("orders",)
    assert updated["orders"].text == pm.sql("SELECT 2 amount").text
    assert original["orders"].text == pm.sql("SELECT 1 amount").text
    assert updated.text == pm.draft().define(orders=pm.sql("SELECT 2 amount")).text


def test_batch_edits_preserve_warmed_text_and_scopes():
    original = pm.draft().define(
        first=pm.sql("SELECT 1 amount"), second=pm.sql("SELECT 2 amount")
    )
    original_text = original.text
    assert original["second"].text == pm.sql("SELECT 2 amount").text
    restored = pickle.loads(pickle.dumps(original))
    assert restored.text == original_text
    assert restored["second"].text == original["second"].text
    updated = original.define(
        third=pm.sql("SELECT 3 amount"), second=pm.sql("SELECT 42 amount")
    )
    assert updated.names == ("first", "second", "third")
    assert original.text == original_text
    assert "SELECT 42 amount" in updated.text
    model = updated.queries(
        result=pm.ref("second").pipe(pm.query(pm.select(pm.col("amount"))))
    ).compile()
    try:
        assert model.query("result").run().rows() == [{"amount": 42}]
    finally:
        model.close()
    ambiguous = pm.draft(original.syntax, updated.syntax)
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
    report = candidate.check()
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
    assert candidate.check(
        documentation=DocumentationPolicy(routes=("research",), kinds=("measure",))
    ).ok
    strict = DocumentationPolicy(routes=("business",), severity="error")
    assert not candidate.check(documentation=strict).ok
    assert not candidate.validate(documentation=strict).ok
    revised = candidate.define(
        orders=candidate["orders"].replace(
            revenue=pm.col("amount").avg().doc("Mean line amount in USD.")
        )
    )
    report = revised.check()
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
    reusable = pm.query(pm.group_by(pm.col("region")), pm.aggregate(pm.col("revenue")))
    candidate = (
        pm.draft()
        .define(orders=orders())
        .define(north=pm.ref("orders").extend(pm.where(pm.col("region") == "N")))
        .queries(summary=pm.ref("north").pipe(reusable))
    )
    generated = candidate.to_python()
    assert ".define(" in generated and ".queries(" in generated
    assert "pm.measure(" in generated and "pm.query(" in generated
    draft = pm.read_model("// authored trivia\r\n" + candidate.text)
    emitted = tmp_path / "model.py"
    emitted.write_text(draft.to_python())
    restored = runpy.run_path(str(emitted))["model"]
    assert "// authored trivia" in restored.text
    restored = restored.define(
        north=pm.ref("orders").extend(pm.where(pm.col("region") == "S"))
    )
    with restored.compile() as runtime:
        assert runtime.query("summary").run().rows() == [{"region": "S", "revenue": 20}]


def test_python_emission_decodes_strings_with_native_malloy_semantics(tmp_path):
    source = r"""source: values is duckdb.sql("SELECT '\u0041' AS value")
query: result is values -> {select: value}
"""
    candidate = pm.read_model(source)
    path = tmp_path / "literal.py"
    path.write_text(candidate.to_python())
    restored = runpy.run_path(str(path))["model"]
    assert candidate.text == source
    with candidate.compile() as original, restored.compile() as rebuilt:
        assert original.query("result").sql() == rebuilt.query("result").sql()
        assert (
            original.query("result").run().rows()
            == rebuilt.query("result").run().rows()
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
    assert "pm.dimension(" in generated and "pm.measure(" in generated
    assert "pm.view(" in generated and ".queries(" in generated
    assert "pm.order_by(" in generated and ".desc()" in generated
    assert "pm.nest(" in generated and "pm.limit(1)" in generated
    path = tmp_path / "model.py"
    path.write_text(generated)
    restored = runpy.run_path(str(path))["model"]
    assert candidate.text == source
    with candidate.compile() as original, restored.compile() as rebuilt:
        left = original.query("result").run()
        right = rebuilt.query("result").run()
        assert left.columns == right.columns
        assert left.rows() == right.rows()
    revised = restored.define(
        sales=restored["sales"].replace(revenue=pm.col("amount").sum() * 2)
    )
    with revised.compile() as model:
        assert model.query("result").run().rows() == [
            {"revenue": 6, "detail": [{"doubled": 6}]}
        ]


def test_annotations_preserve_other_routes_when_replaced_and_reconstructed(tmp_path):
    candidate = (
        pm.draft()
        .define(
            sales=pm.sql("SELECT 2 amount").extend(
                pm.measure(
                    revenue=pm.col("amount")
                    .sum()
                    .doc("Revenue")
                    .annotate("unit=USD", route="research")
                    .annotate("currency=USD")
                ),
                pm.view(
                    totals=pm.query(pm.aggregate(pm.col("revenue"))).annotate(
                        "bar_chart"
                    )
                ),
            )
        )
        .queries(result=pm.ref("sales").pipe(pm.ref("totals")))
    )
    loaded = pm.read_model(candidate.text)
    revised = loaded.define(
        sales=loaded["sales"].replace(
            revenue=pm.col("amount").sum().annotate("unit=EUR", route="research")
        )
    )
    path = tmp_path / "model.py"
    path.write_text(revised.to_python())
    restored = runpy.run_path(str(path))["model"]
    with revised.compile() as original, restored.compile() as rebuilt:
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
            original.query("result").run().rows()
            == rebuilt.query("result").run().rows()
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
    with candidate.compile() as original, restored.compile() as rebuilt:
        assert (
            original.query("result").run().rows()
            == rebuilt.query("result").run().rows()
            == [{"a": 1, "b": 2, "extra": 3}]
        )


def test_python_reconstruction_retains_a_captured_inputs_connection(tmp_path):
    import pyarrow as pa

    frame = pa.table({"value": [1, 2]})
    candidate = (
        pm.draft()
        .define(values=pm.data(frame, name="values", connection="warehouse"))
        .queries(
            result=pm.ref("values").pipe(
                pm.query(pm.aggregate(total=pm.col("value").sum()))
            )
        )
    )
    path = tmp_path / "model.py"
    path.write_text(candidate.to_python(inputs={"values": "frame"}))
    restored = runpy.run_path(str(path), init_globals={"frame": frame})["model"]
    with restored.compile(connection_name="warehouse") as model:
        assert model.query("result").run().rows() == [{"total": 3}]


def test_constructor_text_is_readable_without_reformatting_raw_literals():
    inline = 'duckdb.sql("""SELECT \'first\nsecond\' AS label""")'
    candidate = (
        pm.draft()
        .define(
            orders=pm.sql("SELECT 1 AS value").extend(
                pm.dimension(day=pm.col("value"), days=pm.col("value")),
                pm.join("labels", pm.syntax(inline), kind="one", on=pm.lit(True)),
                pm.view(
                    details=pm.query(
                        pm.select(
                            pm.col("day"), pm.col("days"), pm.col("labels", "label")
                        )
                    )
                ),
            )
        )
        .queries(result=pm.ref("orders").pipe(pm.ref("details")))
    )
    assert candidate.text.startswith("source: orders is duckdb.sql(")
    assert "  dimension: `day` is value, `days` is value" in candidate.text
    assert (
        "  view: details is {\n    select: `day`, `days`, labels.label\n  }"
        in candidate.text
    )
    assert inline in candidate.text
    assert pm.read_model(candidate.text).text == candidate.text
    assert pm.ref("orders").extend().pipe().text == "orders"
    with candidate.compile() as model:
        assert model.query("result").run().rows() == [
            {"day": 1, "days": 1, "label": "first\nsecond"}
        ]


def test_generated_blocks_leave_raw_block_annotations_at_their_authored_columns():
    raw = "#|(research)\n  body\n|#\nselect: amount"
    candidate = (
        pm.draft()
        .define(
            values=pm.sql("SELECT 1 amount").extend(
                pm.view(
                    detail=pm.query(
                        pm.syntax(raw).doc("Details").annotate("currency=USD")
                    )
                )
            )
        )
        .queries(result=pm.ref("values").pipe(pm.ref("detail")))
    )
    assert "\n" + raw + "\n" in candidate.text
    with candidate.compile() as model:
        assert model.query("result").run().rows() == [{"amount": 1}]
