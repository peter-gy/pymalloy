# ruff: noqa: B018, PLR1711
# marimo serializes cell output expressions and terminal returns as notebook syntax.
import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import polars as pl

    import pymalloy as pm

    return mo, pl, pm


@app.cell
def _(mo):
    mo.md("""
    # Edit a semantic model with visible intermediate values

    Each row is one order. Amount and refund are USD. We want to compare
    booked revenue and order counts by region, then inspect how refunds
    change that definition.

    Return an expression, source, query fragment, or draft from a cell to
    inspect its Malloy source, references, annotations, and captured inputs.
    Use **Check** or **Run** when ready. Editing a value creates
    a new inspector revision without silently executing it.
    """)
    return


@app.cell
def _(pl):
    orders_frame = pl.DataFrame(
        {
            "order_id": [1, 2, 3, 4],
            "region": ["North", "North", "South", "South"],
            "amount": [30, 50, 20, 15],
            "refund": [0, 10, 0, 5],
        }
    )
    orders_frame
    return (orders_frame,)


@app.cell
def _(pm):
    revenue = pm.col("amount").sum().doc("Gross booked amount in USD.")
    revenue
    return (revenue,)


@app.cell
def _(orders_frame, pm, revenue):
    orders = (
        pm.data(orders_frame, name="orders")
        .primary_key("order_id")
        .measure(revenue=revenue, order_count=pm.count())
        .doc("One row per order. Amount and refund are USD.")
    )
    orders
    return (orders,)


@app.cell
def _(pm):
    regional = (
        pm.view()
        .group_by(pm.col("region"))
        .aggregate(pm.col("revenue"), pm.col("order_count"))
        .order_by(pm.col("revenue").desc(), pm.col("region").asc())
    )
    regional
    return (regional,)


@app.cell
def _(orders, pm, regional):
    candidate = (
        pm.draft()
        .sources(orders=orders)
        .queries(by_region=pm.source("orders").pipe(regional))
    )
    candidate
    return (candidate,)


@app.cell
def _(candidate, pm):
    net_candidate = candidate.sources(
        orders=candidate["orders"].replace(
            revenue=(pm.col("amount").sum() - pm.col("refund").sum()).doc(
                "Booked amount less refunds, in USD."
            ),
        )
    )
    net_candidate
    return (net_candidate,)


@app.cell
def _(candidate, mo, net_candidate):
    mo.md(
        "### Review the semantic change\n\n```diff\n"
        + net_candidate.diff(candidate)
        + "\n```"
    )
    return


if __name__ == "__main__":
    app.run()
