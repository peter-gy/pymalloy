# PyMalloy

Author and run [Malloy](https://docs.malloydata.dev/) semantic models from Python.
Malloy defines fields, measures, joins, and queries and compiles them to SQL.
[DuckDB](https://duckdb.org/docs/stable/) executes the SQL.

```sh
pip install pymalloy
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

The draft prints ordinary Malloy source. The query returns:

```text
[{'region': 'North', 'revenue': Decimal('42')}, {'region': 'South', 'revenue': Decimal('30')}]
```

Drafts are immutable. Validate assumptions with named counterexample queries,
capture prepared Python data with `pm.data(frame)`, and bundle the accepted model
with its inputs. The package includes the compiler, DuckDB execution, data
capture, and browser widgets.

- [Run Python queries](https://peter-gy.github.io/pymalloy/guide/getting-started)
- [Author a model](https://peter-gy.github.io/pymalloy/guide/authoring) or
  [edit an existing model](https://peter-gy.github.io/pymalloy/guide/editing)
- [Capture Python data](https://peter-gy.github.io/pymalloy/guide/dataframes)
- [Show a widget](https://peter-gy.github.io/pymalloy/guide/widget) or
  [run Python in the browser](https://peter-gy.github.io/pymalloy/guide/browser-python)
- [Export a notebook](https://peter-gy.github.io/pymalloy/guide/export) or
  [ship a source bundle](https://peter-gy.github.io/pymalloy/guide/bundles)
- Use the [Node](https://peter-gy.github.io/pymalloy/reference/node) or
  [browser JavaScript](https://peter-gy.github.io/pymalloy/reference/browser) API

For versioned agent guidance, start with `help(pymalloy.agent)` after
`import pymalloy.agent`.

[Examples](examples) · [Contributing](development_docs/README.md)
