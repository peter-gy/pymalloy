import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    from model import SALES, SOURCE

    import pymalloy as pm
    from pymalloy import MalloyWidget
    from pymalloy.analysis import to_dict

    return MalloyWidget, SALES, SOURCE, mo, pm, to_dict


@app.cell
def _(mo):
    mo.md("""
    # Sales analysis

    Filter a region and inspect the query result in Python.
    """)
    return


@app.cell
def _(mo):
    region = mo.ui.dropdown(["North", "South"], value="North", label="Region")
    invalid = mo.ui.checkbox(label="Use an invalid model")
    mo.hstack([region, invalid])
    return invalid, region


@app.cell
def _(MalloyWidget, SALES, SOURCE, mo):
    analysis = mo.ui.anywidget(
        MalloyWidget(SOURCE, files={"sales.csv": SALES}, query="sales.filtered")
    )
    analysis
    return (analysis,)


@app.cell
def _(SOURCE, analysis, invalid, region):
    analysis.widget.source = "run: missing_source" if invalid.value else SOURCE
    analysis.widget.givens = {"region_filter": region.value}
    return


@app.cell
def _(analysis, mo, to_dict):
    _ = analysis.value
    state = to_dict(analysis.widget.state)
    mo.md(
        f"Python received: `{state.get('status')}`\n\nRows: `{state.get('rows', [])}`"
    )
    return


@app.cell
def _(pm, region):
    notebook_expression = (
        pm.col("amount").sum().doc(f"Booked amount in USD for {region.value}.")
    )
    notebook_expression
    return (notebook_expression,)


@app.cell
def _(pm):
    notebook_draft = (
        pm.draft()
        .define(
            values=pm.sql("SELECT 42 AS answer")
            .extend(pm.measure(total=pm.col("answer").sum()))
            .doc("One row per answer.")
            .annotate("bar_chart x=answer")
        )
        .queries(answer=pm.ref("values").pipe(pm.query(pm.select(pm.col("answer")))))
    )
    notebook_draft
    return (notebook_draft,)


@app.cell
def _(pm):
    import duckdb

    native_connection = duckdb.connect()
    native_connection.execute(
        "CREATE TABLE local_values AS SELECT 9007199254740993::BIGINT AS id, 1.2300::DECIMAL(12,4) AS amount, [1, NULL, 3] AS nested"
    )
    native_model = pm.model(
        "run: duckdb.table('local_values') -> {select: *}", connection=native_connection
    )
    native_query = native_model.query()
    native_query
    return native_connection, native_model, native_query


if __name__ == "__main__":
    app.run()
