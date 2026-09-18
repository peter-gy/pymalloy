# PyMalloy

Author, check, run, and share [Malloy](https://www.malloydata.dev/) models from
Python. Compose models with Python expressions or edit existing Malloy source.
Malloy compiles the queries, and [DuckDB](https://duckdb.org/) executes them.

## Author and run a model

```sh
pip install 'pymalloy[server]'
```

```python
import pymalloy as pm

orders = pm.sql("SELECT * FROM (VALUES ('North', 20), ('North', 22)) t(region, amount)")
candidate = (
    pm.draft()
    .define(
        orders=orders.extend(
            pm.measure(revenue=pm.col("amount").sum().doc("Booked amount in USD.")),
        ).doc("One row per order.")
    )
    .queries(
        by_region=pm.ref("orders").pipe(
            pm.query(
                pm.group_by(pm.col("region")),
                pm.aggregate(pm.col("revenue")),
            )
        )
    )
)

print(candidate.text)  # Ordinary Malloy source
print(pm.run(candidate).rows())  # [{'region': 'North', 'revenue': Decimal('42')}]
```

Drafts are immutable. Check them with Malloy, validate assumptions with named
counterexample queries, and package accepted models with their captured inputs.
Use `pm.data(frame)` to bring prepared Python data into the model as portable
Parquet. Retain the producing notebook or script for preparation logic.

## Explore in a browser widget

```sh
pip install 'pymalloy[widget]'
```

```python
from pymalloy import MalloyWidget

widget = MalloyWidget("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }")
widget
```

Display the widget in Jupyter or marimo. Malloy and DuckDB WebAssembly run in the
browser. The widget extra requires no Deno or server extra. First use downloads
DuckDB WebAssembly and needs browser worker support.

## Learn more

- [Concepts and boundaries](https://peter-gy.github.io/pymalloy/guide/concepts)
- [Author and validate models](https://peter-gy.github.io/pymalloy/guide/authoring)
- [Capture Python data](https://peter-gy.github.io/pymalloy/guide/dataframes)
- [Bundle models and inputs](https://peter-gy.github.io/pymalloy/guide/bundles)
- [Run queries from Python](https://peter-gy.github.io/pymalloy/guide/server-python)
- [Use widgets](https://peter-gy.github.io/pymalloy/guide/getting-started) or
  [export notebooks](https://peter-gy.github.io/pymalloy/guide/export)
- [Node](https://peter-gy.github.io/pymalloy/reference/node) and
  [browser JavaScript](https://peter-gy.github.io/pymalloy/reference/browser) APIs

Install `pymalloy[agent]` for the versioned agent instructions, then import
`pymalloy.agent` and start with `help(pymalloy.agent)`.
