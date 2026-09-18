import ast
import datetime
import decimal
import runpy

import pytest

import pymalloy as pm

DATA = """SELECT * FROM (VALUES
    (1, 40, ' Alpha. ', TIMESTAMP '2024-05-06 12:34:56'),
    (2, 40, 'beta', TIMESTAMP '2024-06-07 01:02:03'),
    (3, 2, NULL, TIMESTAMP '2025-01-02 00:00:00')
) t(id, amount, name, created)"""


def execute(**expressions):
    draft = (
        pm.draft()
        .define(data=pm.sql(DATA))
        .queries(
            result=pm.ref("data").pipe(
                pm.query(pm.select(**expressions), pm.order_by(pm.col("id")))
            )
        )
    )
    model = draft.compile()
    try:
        return model.query("result").run()
    finally:
        model.close()


def test_scalar_operators_precedence_reverse_operands_and_literals():
    a = pm.col("amount")
    rows = execute(
        id=pm.col("id"),
        value=2 + a * 3,
        negative=-a,
        reverse=100 - a,
        ratio=80 / a,
        remainder=a % 3,
        power=a**2,
        selected=(a > 3) & ~(pm.col("id") == 2),
        other=(a <= 2) | (pm.col("id") != 1),
        literal=pm.lit("x'\"\\\n); run: missing"),
    ).rows()
    assert rows[0] == {
        "id": 1,
        "value": 122,
        "negative": -40,
        "reverse": 60,
        "ratio": 2,
        "remainder": 1,
        "power": 1600,
        "selected": True,
        "other": False,
        "literal": "x'\"\\\n); run: missing",
    }
    assert rows[1]["selected"] is False
    assert rows[2]["ratio"] == 40
    assert rows[2]["other"] is True


def test_namespaces_nulls_cases_and_temporal_types_survive_python_emission(tmp_path):
    name = pm.col("name")
    created = pm.col("created")
    fields = {
        "id": pm.col("id"),
        "clean": name.str.strip().str.lower(),
        "upper": name.str.upper(),
        "chars": name.str.length(),
        "literal_dot": name.str.contains("."),
        "starts": name.str.starts_with(" "),
        "ends": name.str.ends_with(" "),
        "replaced": name.str.replace("Alpha", "Beta"),
        "filled": name.fill_null("missing"),
        "nullable": pm.col("amount").nullif(2),
        "absent": name.is_null(),
        "present": name.is_not_null(),
        "category": pm.case((pm.col("amount") > 10, "large"), otherwise="small"),
        "year": created.dt.year(),
        "month": created.dt.month(),
        "day": created.dt.day(),
        "hour": created.dt.hour(),
        "minute": created.dt.minute(),
        "second": created.dt.second(),
        "year_start": created.dt.truncate("year"),
        "date_year": pm.col("created_date").dt.year(),
        "month_start": pm.col("created_date").dt.truncate("month"),
        "date": created.dt.date(),
        "safe": pm.lit("invalid").cast("number", safe=True),
    }
    draft = (
        pm.draft()
        .define(data=pm.sql(f"SELECT *, created::DATE AS created_date FROM ({DATA})"))
        .queries(
            result=pm.ref("data").pipe(
                pm.query(pm.select(**fields), pm.order_by(pm.col("id")))
            )
        )
    )
    path = tmp_path / "namespaces.py"
    path.write_text(pm.read_model(draft.text).to_python())
    model = runpy.run_path(str(path))["model"].compile()
    try:
        rows = model.query("result").run().rows()
    finally:
        model.close()
    assert rows[0]["clean"] == "alpha."
    assert rows[0]["upper"] == " ALPHA. "
    assert rows[0]["chars"] == 8
    assert rows[0]["literal_dot"] is True and rows[1]["literal_dot"] is False
    assert rows[0]["starts"] and rows[0]["ends"]
    assert rows[0]["replaced"] == " Beta. "
    assert rows[2]["filled"] == "missing" and rows[2]["nullable"] is None
    assert rows[2]["absent"] and not rows[2]["present"]
    assert [r["category"] for r in rows] == ["large", "large", "small"]
    assert [
        rows[0][k] for k in ["year", "month", "day", "hour", "minute", "second"]
    ] == [2024, 5, 6, 12, 34, 56]
    assert rows[0]["year_start"] == datetime.datetime.fromisoformat("2024-01-01")
    assert rows[0]["date_year"] == 2024
    assert rows[0]["month_start"] == datetime.datetime.fromisoformat("2024-05-01")
    assert rows[0]["date"] == datetime.date(2024, 5, 6)
    assert rows[0]["safe"] is None


def test_aggregate_scope_distinct_values_and_filtered_aggregates():
    amount = pm.col("amount")
    draft = (
        pm.draft()
        .define(
            data=pm.sql(DATA).extend(
                pm.measure(
                    total=amount.sum(),
                    average=amount.avg(),
                    low=amount.min(),
                    high=amount.max(),
                    rows=pm.count(),
                    distinct=amount.count_distinct(),
                    computed=(amount + 1).sum(),
                    filtered=amount.sum().filter(amount > 3),
                )
            )
        )
        .queries(
            result=pm.ref("data").pipe(
                pm.query(
                    pm.aggregate(
                        *(
                            pm.col(name)
                            for name in [
                                "total",
                                "average",
                                "low",
                                "high",
                                "rows",
                                "distinct",
                                "computed",
                                "filtered",
                            ]
                        )
                    )
                )
            )
        )
    )
    model = draft.compile()
    try:
        row = model.query("result").run().rows()[0]
        assert row == {
            "total": 82,
            "average": 82 / 3,
            "low": 2,
            "high": 40,
            "rows": 3,
            "distinct": 2,
            "computed": 85,
            "filtered": 80,
        }
    finally:
        model.close()
    joined = (
        pm.draft()
        .define(
            items=pm.sql(
                "SELECT * FROM (VALUES(1,10),(1,20),(2,30)) t(parent_id, amount)"
            ),
            parents=pm.sql("SELECT * FROM (VALUES(1),(2)) t(id)").extend(
                pm.primary_key("id"),
                pm.join(
                    "items",
                    pm.ref("items"),
                    on=pm.col("id") == pm.col("items", "parent_id"),
                    kind="many",
                ),
            ),
        )
        .queries(
            result=pm.ref("parents").pipe(
                pm.query(
                    pm.aggregate(
                        parents=pm.count(),
                        items=pm.count("items"),
                        total=pm.col("items", "amount").sum(),
                    )
                )
            )
        )
    )
    model = joined.compile()
    try:
        assert model.query("result").run().rows() == [
            {"parents": 2, "items": 3, "total": 60}
        ]
    finally:
        model.close()


def test_symbolic_values_cannot_be_used_as_python_conditions_or_implicit_code():
    amount = pm.col("amount")
    for operation in [
        lambda: bool(amount),
        lambda: iter(amount),
        lambda: 0 < amount < 10,
        lambda: hash(amount),
    ]:
        with pytest.raises(TypeError):
            operation()
    assert amount.equals(pm.col("amount"))
    assert not amount.equals(pm.col("other"))
    assert pm.col("joined", "amount").text != pm.col("joined.amount").text
    for operation in [
        lambda: pm.measure(total="amount.sum()"),
        lambda: pm.group_by("region"),
        lambda: pm.where("amount > 0"),
        lambda: pm.order_by("amount desc"),
    ]:
        with pytest.raises(TypeError, match="symbolic|scalar"):
            operation()
    for invalid in [float("nan"), float("inf"), decimal.Decimal("NaN")]:
        with pytest.raises(TypeError):
            pm.lit(invalid)


def test_given_references_and_raw_escape_compose_symbolically():
    draft = (
        pm.draft("##! experimental.givens\ngiven: minimum :: number is 10\n")
        .define(
            data=pm.sql(DATA).extend(pm.where(pm.col("amount") > pm.given("minimum")))
        )
        .queries(
            result=pm.ref("data").pipe(
                pm.query(pm.aggregate(total=pm.col("amount").sum()))
            )
        )
    )
    model = draft.compile()
    try:
        assert model.query("result").run(givens={"minimum": 30}).rows() == [
            {"total": 80}
        ]
    finally:
        model.close()
    result = execute(
        id=pm.col("id"), answer=pm.raw_expr("amount // trailing Malloy comment") + 1
    )
    assert result.rows()[0]["answer"] == 41


def test_literal_values_and_types_survive_constructed_and_parsed_python(tmp_path):
    values = {
        "day": pm.lit(datetime.date(2024, 5, 6)),
        "time": pm.lit(datetime.datetime.fromisoformat("2024-05-06T12:30")),
        "instant": pm.lit(
            datetime.datetime(
                2024,
                5,
                6,
                12,
                30,
                tzinfo=datetime.timezone(datetime.timedelta(hours=2)),
            )
        ),
        "precise": pm.lit(decimal.Decimal("1.234567890123456789")),
        "huge": pm.lit(123456789012345678901234567890),
        "scientific": pm.number("1e0"),
    }
    draft = (
        pm.draft()
        .define(data=pm.sql("SELECT 1 AS id").extend(pm.dimension(**values)))
        .queries(
            result=pm.ref("data").pipe(
                pm.query(pm.select(*(pm.col(name) for name in values)))
            )
        )
    )
    results = []
    candidates = [draft]
    for name, candidate in [
        ("constructed", draft),
        ("parsed", pm.read_model(draft.text)),
    ]:
        path = tmp_path / f"{name}.py"
        path.write_text(candidate.to_python())
        candidates.append(runpy.run_path(str(path))["model"])
    for candidate in candidates:
        model = candidate.compile()
        try:
            results.append(model.query("result").run())
        finally:
            model.close()
    original = results[0]
    for result in results[1:]:
        assert result.columns == original.columns
        assert result.rows() == original.rows()
    assert original.rows()[0]["instant"] == datetime.datetime(
        2024, 5, 6, 10, 30, tzinfo=datetime.UTC
    )
    assert original.rows()[0]["scientific"] == 1.0
    assert next(c.type for c in original.columns if c.name == "scientific") == "DOUBLE"


def test_imported_expressions_emit_editable_python_operations(tmp_path):
    source = """// keep model comment
source: data is duckdb.sql('SELECT 5 AS amount') extend {
  dimension: doubled is amount * 2
  measure: total is amount.sum()
}
query: result is data -> {select: doubled}
"""
    original = pm.read_model(source)
    assert original.text == source
    assert isinstance(original["data"]["doubled"], pm.Expr)
    assert original["data"]["doubled"].equals(pm.col("amount") * 2)
    tree = ast.parse(original.to_python())
    for node in ast.walk(tree):
        match node:
            case ast.Call(
                func=ast.Attribute(value=ast.Name(id="pm"), attr="lit"),
                args=[ast.Constant(value=2)],
            ):
                node.args[0] = ast.Constant(3)
    path = tmp_path / "edited.py"
    path.write_text(ast.unparse(ast.fix_missing_locations(tree)))
    edited = runpy.run_path(str(path))["model"]
    assert "// keep model comment" in edited.text
    model = edited.compile()
    try:
        assert model.query("result").run().rows() == [{"doubled": 15}]
    finally:
        model.close()


def test_syntax_identity_and_named_scalar_replacement_have_explicit_contracts():
    first = pm.dimension(x=pm.col("x"))
    second = pm.dimension(x=pm.col("x"))
    assert first != second
    draft = pm.draft().define(
        s=pm.sql("SELECT 42 AS x").extend(pm.measure(total=pm.col("x").sum()))
    )
    assert draft != pm.draft().define(s=draft["s"])
    with pytest.raises(TypeError, match="scalar"):
        draft["s"].replace(total=pm.syntax("x.sum()"))
    assert isinstance(draft["s"].replace(total=pm.col("x").avg())["total"], pm.Expr)


def test_opaque_temporal_comparison_keeps_malloy_range_semantics(tmp_path):
    source = """source: events is duckdb.sql("SELECT * FROM (VALUES (TIMESTAMP '2022-06-01 12:00:00'), (TIMESTAMP '2023-06-01 12:00:00')) t(created)")
query: selected is events -> {where: created = @2022 aggregate: n is count()}
"""
    original = pm.read_model(source)
    generated = tmp_path / "temporal.py"
    generated.write_text(original.to_python())
    restored = runpy.run_path(str(generated))["model"]
    for draft in [original, restored]:
        model = draft.compile()
        try:
            assert model.query("selected").run().rows() == [{"n": 1}]
        finally:
            model.close()


def test_documented_scalars_remain_composable_and_bind_once(tmp_path):
    total = (pm.col("amount").doc("Order amount").sum() + 1).doc("Revenue")
    assert isinstance(total, pm.Expr)
    draft = (
        pm.draft()
        .define(data=pm.sql(DATA).extend(pm.measure(total=total)))
        .queries(result=pm.ref("data").pipe(pm.query(pm.aggregate(pm.col("total")))))
    )
    path = tmp_path / "documented.py"
    path.write_text(draft.to_python())
    restored = runpy.run_path(str(path))["model"]
    assert restored.text == draft.text
    model = restored.compile()
    try:
        assert model.query("result").run().rows() == [{"total": 83}]
        source = next(s for s in model.inspect().model.sources if s.name == "data")
        total = next(f for f in source.schema.fields if f.name == "total")
        assert [note.value.strip() for note in total.annotations] == ["#(doc) Revenue"]
    finally:
        model.close()


def test_deep_expression_text_renders_without_python_stack_growth():
    expression = pm.lit(0)
    for _ in range(2500):
        expression = expression + 1
    expected = "(" * 2500 + "0" + " + 1)" * 2500
    assert expression.text == expected
    assert (expression + 2).text == f"({expected} + 2)"
    assert expression.text == expected
