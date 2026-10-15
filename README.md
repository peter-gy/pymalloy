# PyMalloy

Author, check, run, and share [Malloy](https://www.malloydata.dev/) models from
Python. Compose models with Python expressions or edit existing Malloy source.
Malloy compiles the queries, and [DuckDB](https://duckdb.org/) executes them.

## Author and run a model

```sh
pip install 'pymalloy[headless]'
```

```python
import pymalloy as pm

orders = pm.sql(
    "SELECT * FROM (VALUES ('North', 20), ('North', 22), ('South', 30)) t(region, amount)"
)
model = (
    pm.draft()
    .sources(
        orders=orders.measure(
            revenue=pm.col("amount").sum().doc("Booked amount in USD.")
        )
    )
    .queries(
        by_region=pm.source("orders").pipe(
            pm.view().group_by("region").aggregate("revenue").order_by("region")
        )
    )
)
print(model.text)
with pm.connect() as con:
    print(con.model(model).query("by_region").run().to_pylist())
```

Drafts are immutable. Check them with Malloy, validate assumptions with named
counterexample queries, and package accepted models with their captured inputs.
Use `pm.data(frame)` to bring prepared Python data into the model as portable
Parquet. Retain the producing notebook or script for preparation logic.

## Explore in a browser widget

```sh
pip install 'pymalloy'
```

```python
from pymalloy import MalloyWidget

widget = MalloyWidget("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }")
widget
```

Display the widget in Jupyter or marimo. Malloy and DuckDB WebAssembly run in the
browser. The base install includes widgets and agent guidance, without Deno. First use downloads
DuckDB WebAssembly and needs browser worker support.

## Learn more

- [Concepts and boundaries](https://peter-gy.github.io/pymalloy/guide/concepts)
- [Author and validate models](https://peter-gy.github.io/pymalloy/guide/authoring)
- [Capture Python data](https://peter-gy.github.io/pymalloy/guide/dataframes)
- [Bundle models and inputs](https://peter-gy.github.io/pymalloy/guide/bundles)
- [Run queries from Python](https://peter-gy.github.io/pymalloy/guide/headless-python)
- [Use widgets](https://peter-gy.github.io/pymalloy/guide/getting-started) or
  [export notebooks](https://peter-gy.github.io/pymalloy/guide/export)
- [Node](https://peter-gy.github.io/pymalloy/reference/node) and
  [browser JavaScript](https://peter-gy.github.io/pymalloy/reference/browser) APIs

For the included versioned agent instructions, import
`pymalloy.agent` and start with `help(pymalloy.agent)`.

[Examples](examples) · [Contributing](development_docs/README.md)
