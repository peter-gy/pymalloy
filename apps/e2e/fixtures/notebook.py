import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    from model import SALES, SOURCE

    from pymalloy import MalloyWidget
    from pymalloy.analysis import to_dict

    return MalloyWidget, SALES, SOURCE, mo, to_dict


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


if __name__ == "__main__":
    app.run()
