# Run queries from Python

Install `pymalloy[headless]` to compile [Malloy](https://docs.malloydata.dev/) and
execute SQL with [DuckDB](https://duckdb.org/docs/stable/), an embedded database.
Use a connection to scope the database and its compiled models:

```python
import pymalloy as pm

text = """source: orders is duckdb.sql('SELECT 42 AS amount') extend {
  view: detail is { select: amount }
}
query: total is orders -> { aggregate: revenue is amount.sum() }
"""
with pm.connect(timeout=30) as con:
    model = con.model(text)
    print([(query.name, query.kind) for query in model.queries])
    query = model.query("orders.detail")
    print(query.run().to_pylist())
    print(model.query(malloy="run: orders -> { select: amount }").preview(limit=1).to_pylist())
    selected = pm.source("orders").pipe(pm.view().select("amount"))
    result = model.query(selected).run()
print(result.to_pylist())
```

The inventory contains `total` (`named`) and `orders.detail` (`view`). Each
execution prints `[{'amount': 42}]`. Closing the connection releases its child
models and owned database. Materialized results remain readable.

## Load a model and select a query

A string is Malloy text. Pass `Path("orders.malloy")` for a file, a `Draft` for
composed source, or `ModelSource` for a closed snapshot.
A source URL controls imports. Inline text defaults to `model.malloy` under
`data_root`, or the current directory. A draft retains its own URL.
Pass `url=` for inline text. Conflicting identities raise `ValueError`.

Files ending in `.malloynb` or `.malloysql` use notebook grammar.
`document_kind="model"` or `"notebook"` overrides inference.
Drafts use model grammar. Snapshots retain their kind.

`model.queries` contains `pymalloy.analysis.QueryDescriptor` records with `name`,
`kind`, `location`, and `schema`. A compiled run or named query exposes its output
schema. Required unbound givens yield `schema=None`. Source views and SQL cells
resolve output during preparation or execution.

Select a named query with `model.query("total")` or a saved source view with
`model.query("orders.detail")`. `model.query()` selects the final run or sole
available query. Otherwise choose a name. `run:0` and `sql:0` identify the first
run and SQL cell. Ordinals and source coordinates are zero-based.

Use `model.query(malloy="run: orders -> ...")` for ad hoc Malloy text or pass a
composed `Source` as the positional selection. A positional string selects an
inventory name.

## Prepare SQL or bound a preview

`query.sql(givens=..., timeout=...)` prepares SQL. Ad hoc source can trigger
schema discovery. `query.run(...)` executes current data and materializes a
result. `query.preview(limit=20, ...)` returns at most that many top-level rows
and rejects COPY. Limits range from 1 to 10,000. Aggregates can still scan the
whole input and nested results can contain additional rows.

The connection default timeout is 120 seconds. `con.model(..., timeout=30)` sets
a model's compilation and default operation budget. Per-operation overrides
cover waiting, compilation, and execution under one deadline.
A SQL timeout interrupts the statement and leaves a healthy model reusable.
An in-flight compiler timeout closes that model. Create another model after a
compiler failure. See [errors](../reference/runtime.md#errors).

## Keep the right owner alive

Reuse a model while source and schemas stay fixed. Each model owns one compiler
process. `model.close()` invalidates its queries and leaves sibling models usable.
Models and queries retain the connection. `con.close()` settles work and closes
its child models and owned engine. Both connection and model support `with`.

`model.source()` retains logical source, imports, and captured `pm.data` input
owners independently of the compiler. Compile the snapshot again to reuse them.
External tables and files still need their original data-access setup.

## Borrow a DuckDB connection

```python
import duckdb
import pymalloy as pm

with duckdb.connect() as native:
    native.execute("CREATE TABLE orders AS SELECT 42 AS amount")
    with pm.connect(native) as con:
        result = con.model(
            "run: duckdb.table('orders') -> { select: amount }"
        ).query().run()
    print(native.execute("SELECT amount FROM orders").fetchall())
```

Expected output is `[(42,)]`. The caller owns settings, registrations,
transactions, and closure. Borrowed connections reject `data_root`, `config`,
nonempty `extensions`, and `read_only=True`. Coordinate direct engine use with
PyMalloy operations. A failed statement can abort an explicit transaction.
The caller must issue `ROLLBACK` before reusing that transaction.

## Read columnar results

```python
import polars as pl
import pyarrow as pa
import pymalloy as pm

with pm.connect() as con:
    result = con.model("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }").query().run()
assert result.to_polars().to_dicts() == [{"answer": 42}]
assert pl.DataFrame(result).to_dicts() == [{"answer": 42}]
assert pa.table(result).to_pylist() == [{"answer": 42}]
print(result.to_pylist())
```

[Arrow](https://arrow.apache.org/docs/) is the columnar format retained by a
result. `to_arrow()` returns its table. `to_pylist()` materializes detached
Python rows. `to_polars()` converts to [Polars](https://docs.pola.rs/), an optional
dataframe library. The [Arrow PyCapsule stream protocol](https://arrow.apache.org/docs/format/CDataInterface/PyCapsuleInterface.html)
lets consumers such as `pl.DataFrame(result)` and `pa.table(result)` read the
retained table. Conversion never reruns SQL.
