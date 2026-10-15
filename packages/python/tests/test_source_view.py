"""Exercise typed authoring through rendered Malloy and native execution."""

import runpy

import pytest

import pymalloy as pm


def target_model():
    orders = (
        pm.table("orders.parquet")
        .primary_key("order_id")
        .dimension(net=pm.col("amount") - pm.col("refund"))
        .measure(
            revenue=pm.col("net").sum().doc("Net booked amount in USD."),
            order_count=pm.count(),
        )
        .join_one(
            "customer",
            pm.source("customers"),
            on=pm.col("customer_id") == pm.col("customer", "id"),
        )
        .view(
            by_region=pm.view()
            .group_by("region")
            .aggregate("revenue", "order_count")
            .order_by(pm.col("revenue").desc())
        )
    )
    model = (
        pm.draft()
        .sources(customers=pm.table("customers.parquet"), orders=orders)
        .queries(top_regions=pm.source("orders").pipe(pm.view("by_region").limit(3)))
    )
    return model


TARGET_TEXT = """source: customers is duckdb.table("customers.parquet"), orders is duckdb.table("orders.parquet") extend {
  primary_key: order_id
  dimension: net is (amount - refund)
  measure:
    #" Net booked amount in USD.
    revenue is net.sum()
    order_count is count()
  join_one: customer is customers on (customer_id = customer.id)
  view: by_region is {
    group_by: region
    aggregate: revenue, order_count
    order_by: revenue desc
  }
}
query: top_regions is orders -> by_region + {
  limit: 3
}
"""


@pytest.fixture
def order_files(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(
        pa.table(
            {
                "order_id": [1, 2, 3, 4, 5],
                "customer_id": [1, 1, 2, 2, 3],
                "region": ["North", "North", "South", "West", "East"],
                "amount": [20, 30, 40, 10, 5],
                "refund": [2, 3, 4, 1, 0],
            }
        ),
        tmp_path / "orders.parquet",
    )
    pq.write_table(
        pa.table({"id": [1, 2, 3], "name": ["Ada", "Bo", "Cy"]}),
        tmp_path / "customers.parquet",
    )
    return tmp_path


def test_target_usage_renders_exact_malloy_and_executes(tmp_path, order_files):
    candidate = target_model()
    assert candidate.text == TARGET_TEXT
    with pm.connect(data_root=tmp_path) as con:
        with con.model(candidate) as model:
            assert model.query("top_regions").run().to_pylist() == [
                {"region": "North", "revenue": 45, "order_count": 2},
                {"region": "South", "revenue": 36, "order_count": 1},
                {"region": "West", "revenue": 9, "order_count": 1},
            ]
        code = tmp_path / "model.py"
        code.write_text(candidate.to_python())
        restored = runpy.run_path(str(code))["model"]
        assert restored.text == TARGET_TEXT
        with con.model(restored) as model:
            assert model.query("top_regions").run().to_pylist()[0]["revenue"] == 45


def test_saved_view_refinement_runs_the_region_pipeline(order_files):
    candidate = target_model().queries(
        top_regions=pm.source("orders").pipe(pm.view("by_region").limit(3))
    )
    with pm.connect(data_root=order_files) as con, con.model(candidate) as model:
        assert model.query("top_regions").run().to_pylist() == [
            {"region": "North", "revenue": 45, "order_count": 2},
            {"region": "South", "revenue": 36, "order_count": 1},
            {"region": "West", "revenue": 9, "order_count": 1},
        ]


def test_positional_paths_and_literal_dots_resolve_through_join():
    orders = pm.sql('SELECT 1 customer_id, 7 AS "literal.dot"').join_one(
        "customer",
        pm.sql("SELECT 1 id, 'Ada' AS name"),
        on=pm.col("customer_id") == pm.col("customer", "id"),
    )
    candidate = (
        pm.draft()
        .sources(orders=orders)
        .queries(
            rows=pm.source("orders").pipe(
                pm.view().select("customer.name", pm.col("literal.dot"))
            )
        )
    )
    with pm.connect() as con, con.model(candidate) as model:
        assert model.query("rows").run().to_pylist() == [
            {"name": "Ada", "literal.dot": 7}
        ]


def test_loaded_bindings_have_typed_builders_and_preserve_unrelated_bytes():
    text = "// header\r\nsource: orders is duckdb.sql('SELECT 2 amount') extend {measure: revenue is amount.sum()}\r\n// retained\r\nquery: totals is orders -> {aggregate: revenue}\r\n"
    candidate = pm.read_model(text)
    assert isinstance(candidate["orders"], pm.Source)
    assert isinstance(candidate["totals"], pm.Source)
    edited = candidate.sources(
        orders=candidate["orders"].replace(revenue=pm.col("amount").avg())
    )
    assert edited.text == text.replace("amount.sum()", "amount.avg()")
    expanded = candidate.sources(
        orders=candidate["orders"].dimension(doubled=pm.col("amount") * 2)
    )
    assert expanded.text.startswith("// header\r\n")
    assert expanded.text.endswith(
        "\r\n// retained\r\nquery: totals is orders -> {aggregate: revenue}\r\n"
    )
    with pm.connect() as con, con.model(expanded) as model:
        assert model.query("totals").run().to_pylist() == [{"revenue": 2}]


def test_view_methods_edit_the_final_stage_and_refine_saved_views():
    summary = pm.view().group_by("region").aggregate(total=pm.col("amount").sum())
    stages = (
        summary.pipe(pm.view().select("region", "total")).order_by("region").limit(1)
    )
    candidate = (
        pm.draft()
        .sources(
            orders=pm.sql(
                "SELECT * FROM (VALUES ('N', 2), ('S', 3)) t(region, amount)"
            ).view(summary=summary)
        )
        .queries(
            staged=pm.source("orders").pipe(stages),
            refined=pm.source("orders").pipe(pm.view("summary").limit(1)),
        )
    )
    assert isinstance(candidate["orders"]["summary"], pm.View)
    with pm.connect() as con, con.model(candidate) as model:
        assert model.query("staged").run().to_pylist() == [{"region": "N", "total": 2}]
        assert len(model.query("refined").run().to_pylist()) == 1


@pytest.mark.parametrize("kind,total", [("one", 20), ("many", 10)])
def test_join_cardinality_controls_parent_measure_on_fanout(kind, total):
    related = pm.sql("SELECT * FROM (VALUES (1, 'Ada'), (1, 'Bo')) t(id, name)")
    orders = (
        pm.sql("SELECT 1 id, 1 customer_id, 10 amount")
        .primary_key("id")
        .measure(total=pm.col("amount").sum())
    )
    orders = getattr(orders, "join_" + kind)(
        "customer", related, on=pm.col("customer_id") == pm.col("customer", "id")
    )
    candidate = (
        pm.draft()
        .sources(orders=orders)
        .queries(
            rows=pm.source("orders").pipe(
                pm.view().aggregate("total", labels=pm.count("customer"))
            )
        )
    )
    with pm.connect() as con, con.model(candidate) as model:
        assert model.query("rows").run().to_pylist() == [{"total": total, "labels": 2}]


def test_cross_join_can_include_every_pair(tmp_path):
    orders = pm.sql("SELECT 1 amount").join_cross(
        "labels", pm.sql("SELECT 'Ada' AS name")
    )
    candidate = (
        pm.draft()
        .sources(orders=orders)
        .queries(rows=pm.source("orders").pipe(pm.view().select("labels.name")))
    )
    code = tmp_path / "model.py"
    code.write_text(candidate.to_python())
    restored = runpy.run_path(str(code))["model"]
    with pm.connect() as con, con.model(restored) as model:
        assert model.query("rows").run().to_pylist() == [{"name": "Ada"}]


def test_authoring_rejects_incompatible_python_categories():
    with pytest.raises(AttributeError):
        pm.table("orders").limit(1)
    with pytest.raises(AttributeError):
        pm.view().dimension(net=pm.col("amount"))
    with pytest.raises(TypeError):
        pm.draft().sources(orders=pm.view())
    with pytest.raises(TypeError):
        pm.table("orders").view(summary=pm.source("orders"))
    with pytest.raises(TypeError):
        pm.source("orders").pipe(pm.source("summary"))
    with pytest.raises(TypeError):
        pm.view().group_by(region="region")


def test_raw_parts_reconstruct_shared_captured_inputs(tmp_path):
    import pyarrow as pa

    frame = pa.table({"amount": [10, 20]})
    source = pm.Source.raw("(", pm.data(frame, name="orders"), ")")
    candidate = (
        pm.draft()
        .sources(orders=source)
        .queries(
            totals=pm.source("orders").pipe(
                pm.view().aggregate(total=pm.col("amount").sum())
            )
        )
    )
    code = tmp_path / "model.py"
    code.write_text(candidate.to_python(inputs={"orders": "frame"}))
    restored = runpy.run_path(str(code), init_globals={"frame": frame})["model"]
    assert restored.inputs[0].to_arrow().to_pylist() == [{"amount": 10}, {"amount": 20}]
    with pm.connect() as con, con.model(restored) as model:
        assert model.query("totals").run().to_pylist() == [{"total": 30}]


def test_parsed_join_reconstructs_editable_source_and_view_bindings(tmp_path):
    candidate = pm.read_model("""source: orders is duckdb.sql('SELECT 1 id') extend {
  join_one: labels is duckdb.sql('SELECT 1 id, 2 amount') on id = labels.id
  measure: revenue is labels.amount.sum()
  view: totals is {aggregate: revenue}
}
query: report is orders -> totals
""")
    code = tmp_path / "model.py"
    code.write_text(candidate.to_python())
    restored = runpy.run_path(str(code))["model"]
    assert isinstance(restored["orders"]["labels"], pm.Source)
    assert isinstance(restored["orders"]["totals"], pm.View)
    revised = restored.sources(
        orders=restored["orders"].replace(revenue=pm.col("labels", "amount").sum() * 2)
    )
    with pm.connect() as con, con.model(revised) as model:
        assert model.query("report").run().to_pylist() == [{"revenue": 4}]


def test_documented_named_fields_keep_positional_fields_in_the_same_clause():
    candidate = (
        pm.draft()
        .sources(orders=pm.sql("SELECT 1 id, 2 amount"))
        .queries(
            rows=pm.source("orders").pipe(
                pm.view().select("id", total=pm.col("amount").doc("Booked amount."))
            )
        )
    )
    with pm.connect() as con, con.model(candidate) as model:
        assert model.query("rows").run().to_pylist() == [{"id": 1, "total": 2}]


def test_parameterized_source_reconstruction_keeps_native_arguments(tmp_path):
    candidate = pm.read_model("""##! experimental.parameters
source: orders(p :: number is 2) is duckdb.sql('SELECT 1 amount')
source: plain is duckdb.sql('SELECT 7 amount')
query: report is orders(p is 3) -> {select: amount}
""")
    generated = candidate.to_python()
    assert ".sources(" in generated
    assert ".queries(" in generated
    assert ".append(" in generated
    code = tmp_path / "model.py"
    code.write_text(generated)
    restored = runpy.run_path(str(code))["model"]
    assert restored.names == ("orders", "plain", "report")
    assert "orders(p :: number is 2)" in restored.text
    assert isinstance(restored["plain"], pm.Source)
    with pm.connect() as con, con.model(restored) as model:
        assert model.query("report").run().to_pylist() == [{"amount": 1}]


def test_parsed_saved_view_refinement_roundtrips_nested_rows(tmp_path):
    orders = pm.sql(
        "SELECT * FROM (VALUES ('N', 'a', 1), ('N', 'a', 5), ('N', 'b', 9), ('S', 'a', 4), ('S', 'b', 1)) t(region, category, amount)"
    ).view(
        by_region=pm.view()
        .group_by("region")
        .aggregate(revenue=pm.col("amount").sum(), n=pm.count())
        .order_by(pm.col("revenue").desc())
        .nest(
            top=pm.view()
            .group_by("category")
            .aggregate(revenue=pm.col("amount").sum())
            .order_by(pm.col("revenue").desc())
            .limit(1)
        )
    )
    original = (
        pm.draft()
        .sources(orders=orders)
        .queries(q=pm.source("orders").pipe(pm.view("by_region").limit(1)))
    )
    loaded = pm.read_model(original.text)
    path = tmp_path / "model.py"
    path.write_text(loaded.to_python())
    namespace = runpy.run_path(str(path))
    expected = [
        {"region": "N", "revenue": 15, "n": 3, "top": [{"category": "b", "revenue": 9}]}
    ]
    with pm.connect() as con:
        for candidate in (loaded, namespace["model"]):
            with con.model(candidate) as model:
                assert model.query("q").run().to_pylist() == expected


def test_order_by_names_output_column_after_path_grouping():
    rows = (
        pm.sql("SELECT 1 id")
        .join_one("customer", pm.sql("SELECT 'Ada' AS name"), on=pm.lit(True))
        .pipe(pm.view().group_by("customer.name").order_by("name"))
    )
    with pm.connect() as con:
        assert con.model(pm.draft().queries(q=rows)).query().run().to_pylist() == [
            {"name": "Ada"}
        ]
    with pytest.raises(
        ValueError,
        match="order_by takes the name of a field in the query output, not a path",
    ):
        pm.view().order_by("customer.name")


def test_order_by_quotes_output_identifiers():
    rows = pm.sql('SELECT 2 AS "order total" UNION ALL SELECT 1').pipe(
        pm.view().select(pm.col("order total")).order_by("order total")
    )
    with pm.connect() as con:
        assert con.model(pm.draft().queries(q=rows)).query().run().to_pylist() == [
            {"order total": 1},
            {"order total": 2},
        ]


def test_select_wildcard_returns_all_source_columns():
    candidate = pm.draft().queries(
        q=pm.sql("SELECT 1 amount, 'N' region").pipe(pm.view().select("*"))
    )
    with pm.connect() as con:
        assert con.model(candidate).query().run().to_pylist() == [
            {"amount": 1, "region": "N"}
        ]


@pytest.mark.parametrize("parsed", [False, True])
def test_refinement_clauses_share_a_stage_and_reject_duplicate_limits(parsed):
    candidate = (
        pm.draft()
        .sources(
            orders=pm.sql(
                "SELECT * FROM (VALUES ('N', 1), ('N', 5), ('S', 4)) t(region, amount)"
            ).view(
                summary=pm.view()
                .group_by("region")
                .aggregate(total=pm.col("amount").sum())
                .order_by("region"),
                filtered=pm.view("summary").limit(1),
            )
        )
        .queries(q=pm.source("orders").pipe("filtered"))
    )
    if parsed:
        candidate = pm.read_model(candidate.text)
    stage = candidate["orders"]["filtered"].where(pm.col("amount") > 2)
    revised = candidate.sources(orders=candidate["orders"].replace(filtered=stage))
    with pm.connect() as con:
        assert con.model(revised).query("q").run().to_pylist() == [
            {"region": "N", "total": 5}
        ]
    with pytest.raises(ValueError, match="already limited"):
        stage.limit(2)
    with pytest.raises(ValueError, match="already limited"):
        pm.view().limit(1).limit(2)


@pytest.mark.parametrize(
    "stage",
    [
        pm.view().group_by("region").annotate("bar_chart"),
        pm.view("regions").doc("Saved").limit(1),
    ],
)
def test_pipeline_rejects_annotations_on_unbound_stages(stage):
    with pytest.raises(ValueError, match="Source.view"):
        pm.source("orders").pipe(stage)
    with pytest.raises(ValueError, match="Draft.queries"):
        pm.view().pipe(stage)


def test_annotated_bindings_compile_saved_views_and_queries():
    orders = pm.sql("SELECT 'N' AS region").view(
        regions=pm.view().group_by("region").aggregate(n=pm.count()).doc("Regions")
    )
    candidate = (
        pm.draft()
        .sources(orders=orders)
        .queries(chart=pm.source("orders").pipe("regions").annotate("bar_chart"))
    )
    with pm.connect() as con:
        assert con.model(candidate).query("chart").run().to_pylist() == [
            {"region": "N", "n": 1}
        ]


def test_inserted_source_clause_preserves_crlf_spelling():
    original = "source: orders is duckdb.sql('SELECT 1 amount') extend {\r\n  measure: revenue is amount.sum()\r\n}\r\nquery: q is orders -> {select: extra}\r\n"
    candidate = pm.read_model(original)
    revised = candidate.sources(orders=candidate["orders"].dimension(extra=pm.lit(2)))
    assert revised.text == original.replace(
        "\r\n}\r\n", "\r\n  dimension: extra is 2\r\n}\r\n"
    )
    with pm.connect() as con:
        assert con.model(revised).query("q").run().to_pylist() == [{"extra": 2}]


def test_authoring_representations_show_class_and_text_with_identity_equality():
    source = pm.source("orders").pipe("by_region")
    view = pm.view("by_region")
    draft = pm.draft("run: orders -> by_region")
    assert repr(source) == "Source('orders -> by_region')"
    assert repr(view) == "View('by_region')"
    assert repr(draft) == "Draft('run: orders -> by_region')"
    assert source != pm.source("orders").pipe("by_region")
    assert view != pm.view("by_region")
    assert draft != pm.draft(draft.text)


@pytest.mark.parametrize("parsed", [False, True])
def test_calculate_and_rename_compile_and_reconstruct_in_current_stage(
    parsed, tmp_path
):
    stage = (
        pm.view()
        .group_by("region")
        .aggregate(revenue=pm.col("booked").sum())
        .order_by("region")
        .calculate(prior=pm.expressions.call("lag", pm.col("revenue")))
    )
    original = (
        pm.draft()
        .sources(
            orders=pm.sql("SELECT * FROM (VALUES ('N', 6), ('S', 4)) t(region, amount)")
            .rename(booked="amount")
            .view(summary=stage)
        )
        .queries(q=pm.source("orders").pipe("summary"))
    )
    if parsed:
        original = pm.read_model(original.text)
    code = original.to_python()
    assert ".rename(" in code
    assert ".calculate(" in code
    path = tmp_path / "model.py"
    path.write_text(code)
    namespace = runpy.run_path(str(path))
    with pm.connect() as con:
        for candidate in (original, namespace["model"]):
            assert con.model(candidate).query("q").run().to_pylist() == [
                {"region": "N", "revenue": 6, "prior": None},
                {"region": "S", "revenue": 4, "prior": 6},
            ]


@pytest.mark.parametrize("parsed", [False, True])
def test_join_reconstruction_preserves_target_documentation(tmp_path, parsed):
    candidate = pm.draft().sources(
        orders=pm.sql("SELECT 1 id").join_one(
            "labels",
            pm.sql("SELECT 1 id").doc("One row per label."),
            on=pm.col("id") == pm.col("labels", "id"),
        )
    )
    if parsed:
        candidate = pm.read_model(candidate.text)
    code = tmp_path / "model.py"
    code.write_text(candidate.to_python())
    restored = runpy.run_path(str(code))["model"]
    with pm.connect() as con:
        report = con.check(restored)
    labels = next(
        item for item in report.model.annotations if item.path == ("orders", "labels")
    )
    assert [(note.route, note.content.strip()) for note in labels.annotations] == [
        ('"', "One row per label.")
    ]


def test_python_reconstruction_groups_bindings_and_uses_saved_view_and_path_strings(
    tmp_path,
):
    import ast

    candidate = pm.read_model("""source: orders is duckdb.sql('SELECT 1 amount') extend {
  view: detail is {select: amount}
  view: summary is {aggregate: total is amount.sum() nest: rows is detail}
}
source: extra is duckdb.sql('SELECT 2 amount')
query: a is orders -> detail
query: b is extra -> {select: amount, label is 'datetime.date'}
""")
    code = candidate.to_python()
    tree = ast.parse(code)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert [
        [item.arg for item in call.keywords]
        for call in calls
        if call.func.attr == "sources"
    ] == [["orders", "extra"]]
    assert [
        [item.arg for item in call.keywords]
        for call in calls
        if call.func.attr == "queries"
    ] == [["a", "b"]]
    assert any(
        call.func.attr == "pipe"
        and isinstance(call.args[0], ast.Constant)
        and call.args[0].value == "detail"
        for call in calls
    )
    nest = next(call for call in calls if call.func.attr == "nest")
    assert isinstance(nest.keywords[0].value, ast.Constant)
    assert nest.keywords[0].value.value == "detail"
    select = next(call for call in calls if call.func.attr == "select")
    assert isinstance(select.args[0], ast.Constant)
    assert select.args[0].value == "amount"
    assert [
        node.names[0].name for node in tree.body if isinstance(node, ast.Import)
    ] == ["pymalloy"]
    path = tmp_path / "model.py"
    path.write_text(code)
    namespace = runpy.run_path(str(path))
    with pm.connect() as con:
        model = con.model(namespace["model"])
        assert model.query("a").run().to_pylist() == [{"amount": 1}]
        assert model.query("b").run().to_pylist() == [
            {"amount": 2, "label": "datetime.date"}
        ]


def test_python_reconstruction_imports_datetime_for_date_literals(tmp_path):
    import datetime

    candidate = pm.draft().queries(
        q=pm.sql("SELECT 1 n").pipe(
            pm.view().select(observed=pm.lit(datetime.date(2026, 1, 2)))
        )
    )
    path = tmp_path / "model.py"
    path.write_text(candidate.to_python())
    namespace = runpy.run_path(str(path))
    with pm.connect() as con:
        assert con.model(namespace["model"]).query().run().to_pylist() == [
            {"observed": datetime.date(2026, 1, 2)}
        ]
