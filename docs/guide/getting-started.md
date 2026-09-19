# Your first widget

Run a Malloy query in Jupyter or marimo with Python 3.12 or newer. The widget
uses [DuckDB](https://duckdb.org/docs/stable/) in your browser. For scripts, use
[headless Python](/guide/headless-python).

## Install

Install PyMalloy into your notebook's Python environment:

```sh
pip install "pymalloy"
```

Use a [Jupyter](https://docs.jupyter.org/) notebook or install the
[marimo](https://docs.marimo.io/) notebook editor with `pip install pymalloy marimo`.

## Display a query

```python
from pymalloy import MalloyWidget

query = MalloyWidget("""
    run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }
""")
query
```

The widget shows `answer: 42`. Open the **SQL** tab to inspect the compiled query.
Execution starts when the notebook's browser connection initializes the widget.
First use downloads [DuckDB WebAssembly](https://duckdb.org/docs/current/clients/wasm/overview)
from jsDelivr. The page must allow that download and browser workers.

## Supply a file

Pass file contents under the name used by the Malloy source:

```python
orders = MalloyWidget(
    """
    run: duckdb.table('orders.csv') -> {
      select: region, amount
      order_by: amount desc
    }
    """,
    files={"orders.csv": "region,amount\nNorth,40\nSouth,30\nNorth,2\n"},
)
orders
```

The table shows amounts `40`, `30`, and `2`. These are **virtual files**: the
browser reads supplied contents under their assigned names. `files` accepts
text, bytes, and [remote URLs](/guide/widget).

## Read results from Python

Results arrive asynchronously from the displayed widget. Register an observer to
consume completed rows:

```python
from pymalloy.analysis import to_dict


def receive_result(change):
    state = change["new"]
    if state["status"] == "ready":
        print(to_dict(state["rows"]))

orders.observe(receive_result, names="state")
orders.source = """
    run: duckdb.table('orders.csv') -> { select: amount order_by: amount desc }
"""
```

The callback prints `[{'amount': 40}, {'amount': 30}, {'amount': 2}]`. Read
`orders.state` for the latest read-only snapshot. `to_dict` converts its nested
mappings and tuples into dictionaries and lists. Call `orders.close()` when finished.

Next: [change inputs](/guide/widget), [learn the concepts](/guide/concepts),
or [troubleshoot](/guide/troubleshooting).
