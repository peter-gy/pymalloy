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
        .queries(top_regions=pm.source("orders").pipe("by_region", pm.view().limit(3)))
    )
    return model


TARGET_TEXT = """source: customers is duckdb.table("customers.parquet")
source: orders is duckdb.table("orders.parquet") extend {
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
query: top_regions is orders -> by_region -> {
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
        top_regions=pm.source("orders").pipe(pm.View.raw("by_region").limit(3))
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
            refined=pm.source("orders").pipe(pm.View.raw("summary").limit(1)),
        )
    )
    assert isinstance(candidate["orders"]["summary"], pm.View)
    with pm.connect() as con, con.model(candidate) as model:
        assert model.query("staged").run().to_pylist() == [{"region": "N", "total": 2}]
        assert len(model.query("refined").run().to_pylist()) == 1


@pytest.mark.parametrize("kind", ["one", "many", "cross"])
def test_join_variants_compile_with_concrete_rows(kind):
    related = pm.sql("SELECT 1 id, 'Ada' AS name").primary_key("id")
    orders = pm.sql("SELECT 1 customer_id, 10 amount")
    orders = getattr(orders, "join_" + kind)(
        "customer", related, on=pm.col("customer_id") == pm.col("customer", "id")
    )
    candidate = (
        pm.draft()
        .sources(orders=orders)
        .queries(
            rows=pm.source("orders").pipe(pm.view().select("customer.name", "amount"))
        )
    )
    with pm.connect() as con, con.model(candidate) as model:
        assert model.query("rows").run().to_pylist() == [{"name": "Ada", "amount": 10}]


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
query: report is orders(p is 3) -> {select: amount}
""")
    code = tmp_path / "model.py"
    code.write_text(candidate.to_python())
    restored = runpy.run_path(str(code))["model"]
    assert restored.names == ("orders", "report")
    with pm.connect() as con, con.model(restored) as model:
        assert model.query("report").run().to_pylist() == [{"amount": 1}]


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
