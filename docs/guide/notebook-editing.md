# Inspect models in notebooks

Leave a PyMalloy value as a cell's final expression to inspect its
[Malloy](https://docs.malloydata.dev/) source, references, annotations, and inputs.
Use [marimo](https://docs.marimo.io/), a reactive Python notebook editor, or
[Jupyter](https://docs.jupyter.org/), a notebook host.

```python
import pymalloy as pm

revenue = pm.col("amount").sum().doc("Gross booked amount in USD.")
revenue
```

**Source** shows `amount.sum()`. **Context** holds documentation and references.
The inspector waits for an explicit **Check** or **Run** action. An isolated
expression acquires execution context when composed into a source or model.

## Compose and inspect

Install `pymalloy`, [PyArrow](https://arrow.apache.org/docs/python/), the Python
implementation of the Arrow columnar format, and your notebook host:

```python
import pyarrow as pa
import pymalloy as pm

orders = pm.data(
    pa.table({"region": ["North", "North"], "amount": [20, 22]}), name="orders"
)
candidate = (
    pm.draft()
    .sources(orders=orders.measure(revenue=pm.col("amount").sum()))
    .queries(
        by_region=pm.source("orders").pipe(
            pm.view().group_by("region").aggregate("revenue")
        )
    )
)
candidate
```

**Check** resolves schemas and opens **Schema**. Its icons distinguish dimensions,
measures, views, and relationships. Schema discovery can read data. Parameters
remain in **Context**, and diagnostics appear in **Issues**. **Run** executes the
selected query and opens **Result**, showing North revenue `42`. **SQL** holds
the generated query.

Drafts use [DuckDB WebAssembly](https://duckdb.org/docs/stable/clients/wasm/overview.html),
a browser SQL engine. First use downloads its assets and requires browser worker
support. Captured inputs become Parquet bytes on the first Check or Run action.
Put intermediate expressions, sources, and views in separate cells to inspect
their scopes before composing them.

| Cell output                                   | Inspector behavior                                                               |
| --------------------------------------------- | -------------------------------------------------------------------------------- |
| `Expr`, `Sort`, `View`, unresolved `Source`   | Authored syntax, references, and annotations                                     |
| Self-contained table, SQL, or captured source | Check and run a generated query selecting up to 20 rows                          |
| `Draft` or `ModelSource`                      | Check and run a selected query in the browser                                    |
| Native `Model` or `Query`                     | Inspect source, check schema, and preview up to 20 rows on its Python connection |
| `Result`                                      | Display up to 20 retained rows and executed SQL                                  |

Complete draft queries use their authored limits. A bounded source or native
preview can still scan the whole input for aggregation. Browser models need
captured inputs, virtual files, or browser-accessible URLs. Native models use
Python filesystem and database access.

## Preview a native query

With `pymalloy[headless]`, retain the connection while using the inspector:

```python
import pymalloy as pm

connection = pm.connect(timeout=30)
model = connection.model("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }")
query = model.query()
query
```

Choose **Preview** to return `answer: 42` using the model's timeout.
`Query.preview` rejects write statements. Closing the inspector leaves the model
usable. Call `connection.close()` when finished to close its models and database.
Materialized results remain readable afterward.

Automatic inspectors follow their cell or view lifetime. Rerunning a marimo cell
closes its previous inspector. Removing the final Jupyter view closes its implicit
widget. Explicit `MalloyWidget` instances remain caller-owned and expose `close()`.
Set `auto_run=False` for inspection before execution. See [widgets](widget.md)
for retained inputs and asynchronous readback.

The [notebook example](https://github.com/peter-gy/pymalloy/blob/main/examples/notebook_editing.py)
compares booked revenue with revenue after refunds using visible intermediate values.
