# Edit models in notebooks

Leave a PyMalloy value as a cell's final expression to inspect its Malloy source,
references, annotations and captured inputs in marimo or Jupyter.

```python
import pymalloy as pm

revenue = pm.col("amount").sum().doc("Gross booked amount in USD.")
revenue
```

The **Source** tab displays `amount.sum()`. **Context** holds its documentation
and references. The inspector waits for an explicit **Check** or **Run** action before compiling or executing.
An isolated expression has no source scope, so execution controls appear when
you compose it into a runnable source or model.

## Compose and inspect

Install `pymalloy`, `pyarrow` and your dataframe library alongside your notebook
host. This example captures two orders and defines a named query:

```python
import pyarrow as pa
import pymalloy as pm

orders = pm.data(pa.table({"region": ["North", "North"], "amount": [20, 22]}),
                 name="orders")
candidate = (
    pm.draft()
    .define(orders=orders.extend(pm.measure(revenue=pm.col("amount").sum())))
    .queries(by_region=pm.ref("orders").pipe(pm.query(
        pm.group_by(pm.col("region")),
        pm.aggregate(pm.col("revenue")),
    )))
)
candidate
```

**Check** resolves the model and opens **Schema**, where icons distinguish dimensions, measures, views and relationships. Parameters remain in **Context** and diagnostics appear in **Issues**. Schema discovery can read input data. **Run**
executes the selected query and opens **Result**. Its generated query is available in **SQL**. This query produces
`North`, `42`. Draft execution uses Malloy and DuckDB WebAssembly in the browser.
Captured inputs become Parquet bytes on the first Check or Run action.

Display intermediate values such as `orders`, `pm.measure(revenue=revenue)` or
a reusable query block in separate cells. Each inspector shows the value's own
structure. An unresolved reference stays unresolved until a containing model
supplies its scope.

| Cell output                                            | Available behavior                                                                                |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| `Expr`, `Sort`, query clauses and incomplete fragments | Authored syntax, references and annotations                                                       |
| Self-contained table, SQL or captured source           | Check and run a generated query selecting up to 20 rows                                           |
| `Draft`, document fragment or `ModelSource`            | Check and run a selected query in the browser                                                     |
| Native `Model` or `Query`                              | Inspect retained source, check schema and preview up to 20 rows on the existing Python connection |
| `Result`                                               | Display up to 20 already materialized rows and SQL                                                |

Complete draft queries use their authored limits. A 20-row source or native
preview bounds the returned rows, while aggregates can still scan the full input.
Browser models need captured inputs, registered virtual files or browser-accessible
URLs. Local Python filesystem paths and native database tables belong to native
models.

## Preview a native query

With `pymalloy[headless]`, a bound query retains its original connection:

```python
import pymalloy as pm

model = pm.model("run: duckdb.sql('SELECT 42 AS answer') -> {select: answer}")
query = model.query()
query
```

Choose **Preview** to return up to 20 rows with a 30-second timeout. The preview uses
`Query.preview`, which rejects write statements. Closing the inspector leaves
`model` usable. Call `model.close()` when finished with its connection and compiler.
A `Result` displayed after execution reads its retained Arrow data even after
the producing model is closed.

## Configure a retained widget

Use an explicit widget when you need query selection, parameters, virtual files
or asynchronous Python readback:

```python
widget = pm.MalloyWidget(candidate, query="by_region", auto_run=False)
widget
```

Explicit `MalloyWidget` construction defaults to `auto_run=True`. Set it to
`False` for the same inspection-first behavior as ordinary cell outputs.
[Widget inputs and readback](widget.md) describes reactive updates and `state`.

Automatic inspectors follow the cell/view lifetime. Rerunning a marimo cell
closes its old inspector. Removing the final Jupyter view closes the implicit
widget. Explicit widgets remain caller-owned and expose `close()`.

The [notebook editing example](https://github.com/peter-gy/pymalloy/blob/main/examples/notebook_editing.py)
walks through captured orders, intermediate grammar values, a regional query,
and a scoped change from gross to net revenue.
