# Update widget inputs and read results

Change a widget's Python properties to select queries or replace data. The
browser runs the query and sends results back to Python.

```python
from pymalloy import Malloy

orders = Malloy(
    """
    source: orders is duckdb.table('orders.csv') extend {
      view: entries is { select: region, amount order_by: amount desc }
      view: regions is { group_by: region order_by: region }
    }
    run: orders -> entries
    """,
    files={"orders.csv": "region,amount\nNorth,40\nSouth,30\nNorth,2\n"},
)
orders
```

Select `orders.regions` to see North and South. The selection also updates
`orders.query` in Python.

## Change inputs

Assign a new value to rerun the widget:

```python
orders.query = "orders.regions"
orders.files = {"orders.csv": "region,amount\nEast,12\nWest,18\n"}
```

The table now shows East and West. Assign complete dictionaries to `files` and
`givens`. Editing a retrieved dictionary does not trigger execution.

Changing `source` or `files` reloads the model. Changing `query` or `givens` reuses
it. During execution, input changes replace the pending update. Only results for
the current input are published.

Use `query=None` for the [default query](/guide/models#select-a-query).

## Files and imports

Text files use UTF-8 encoding. Supply bytes for binary formats:

```python
from pathlib import Path

orders.files = {"orders.parquet": Path("orders.parquet").read_bytes()}
orders.query = None
orders.source = "run: duckdb.table('orders.parquet') -> { select: * }"
```

Malloy imports use the same mapping:

```python
model = Malloy(
    "import 'models/base.malloy'\nrun: numbers -> { select: value }",
    files={
        "models/base.malloy": "source: numbers is duckdb.sql('SELECT 42 AS value')",
    },
)
model
```

Imports resolve relative to the importing model's virtual path. For remote data,
use `{"url": "https://host/path/data.parquet"}`. The host must permit
[CORS](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS), which allows
requests from another website. DuckDB may request byte ranges of a remote file.

Imports and schemas remain fixed until `source` or `files` changes. For changed
remote data, use a versioned URL or create a new widget to clear DuckDB's HTTP
cache. Assigning an equal dictionary does not trigger an update.

Pass [`ModelSource`](/reference/python#modelsource) as `source` to use captured
definitions and imports with their original URLs. Data still comes from `files`.
[Widget export](/guide/export#work-with-browser-widgets) generates this setup.

## Host DuckDB assets

Use `pymalloy.browser` to select your own DuckDB WebAssembly and worker files:

```python
from pymalloy import Malloy, browser

runtime = browser.Runtime(
    mvp=browser.Bundle(
        module="https://assets.example.org/duckdb/duckdb-mvp.wasm",
        worker="https://assets.example.org/duckdb/duckdb-browser-mvp.worker.js",
    ),
    eh=browser.Bundle(
        module="https://assets.example.org/duckdb/duckdb-eh.wasm",
        worker="https://assets.example.org/duckdb/duckdb-browser-eh.worker.js",
    ),
)
orders = Malloy(
    "run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }",
    runtime=runtime,
)
orders
```

Host modules and workers together from `@duckdb/duckdb-wasm@1.33.1-dev57.0/dist/`.
The host must permit browser requests. The notebook must allow `blob:` workers
and scripts from that host. Runtime configuration is fixed for a widget's
lifetime. Omit `runtime` for versioned jsDelivr assets.

Provide both bundles for automatic browser selection. `eh` uses WebAssembly
exception handling. The baseline `mvp` bundle can fail on nested queries with
`_setThrew is not defined`, so nested queries need `eh` and a supporting browser.
See [runtime configuration](/reference/python#browser-runtime).

## Givens

[Givens](/guide/givens) are typed Malloy parameters. Pass `givens={...}` to
`Malloy(...)`, or assign `widget.givens` to rerun a query.

## Inspect results and errors

`widget.state` is read-only and returns a detached snapshot. Its status moves
from `idle` to `loading`, then `ready` or `error`. Input changes clear the previous
result. [Observe state changes](/guide/getting-started#read-results-from-python)
to consume completed rows.

The table previews 100 rows, but `state["rows"]` contains every row. Limit or
aggregate large queries to reduce browser memory and transfer costs. Expand nested
values in the table or open **SQL** to inspect the compiled query.

Read `state["error"]` for failures and `state["diagnostics"]` for compiler messages
and locations. Execution failures may have no compiler diagnostics.

Call `widget.close()` when finished. Displays of one widget share selection and
results. Separate `Malloy(...)` objects own separate browser sessions.

See the [Python widget reference](/reference/python) for field types and lifecycle.
