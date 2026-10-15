# Python widget API

[Malloy](https://docs.malloydata.dev/documentation/) supplies language semantics.
[anywidget](https://anywidget.dev/) carries Python widgets to a notebook browser.
[DuckDB WebAssembly](https://duckdb.org/docs/stable/clients/wasm/overview) is the
browser SQL engine. [Jupyter](https://docs.jupyter.org/) and
[marimo](https://docs.marimo.io/) are notebook hosts that can display these widgets.

<!-- not-executed -->

```python
from pymalloy import MalloyWidget

widget = MalloyWidget("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }")
widget
```

`MalloyWidget(source, *, files=None, query=None, givens=None, runtime=None,
connection_name="duckdb", auto_run=True)` creates an
anywidget for text, `Expr`, `Sort`, `Source`, `View`, `Draft`, `ModelSource`, native
`Model` or `Query`, and materialized `Result` values. `files`, `query`, `givens`,
`auto_run`, and `source` can be assigned after construction. Assign complete mappings to update
files or givens. `files`, `givens`, and `state` are recursively read-only mappings.
Nested sequences are tuples. Reads reuse the published snapshot, and retained
snapshots stay unchanged after later updates. `pymalloy.analysis.to_dict(value)`
creates editable dictionaries and lists when needed.

`state` contains `status`, `queries`, `sql`, `columns`, `rows`, `result`,
`inspection`, `diagnostics`, and `error`. Status is `idle`, `loading`, `ready`, `error`, or
`closed`. Observe `state` for asynchronous updates. Observers receive the same
immutable snapshot. `close()` is idempotent and releases the browser session. Native models and
connections remain owned by the caller.

`connection_name` chooses the Malloy connection served by the browser's DuckDB
runtime. It is read-only for the widget's lifetime and must match the connection
used by the source. Pass it explicitly for aliases such as `analytics`.

## Browser assets

`pymalloy.browser.Bundle(module: str, worker: str)` is a frozen pair of matching
DuckDB WebAssembly binary and worker URLs. Both must be absolute HTTP(S) URLs.
Construction raises `TypeError` for nonstrings and `ValueError` for invalid URLs.
It validates shape. The browser resolves availability.

`pymalloy.browser.Runtime(mvp: Bundle, eh: Bundle | None = None)` is a frozen asset
selection. `mvp` supplies the baseline bundle. `eh` supplies the optional
exception-handling bundle for compatible browsers. Invalid bundle types raise
`TypeError`. Pass `runtime=` when constructing the widget. It stays fixed for
that widget's lifetime.

Assets must be reachable and permitted by the browser's
[cross-origin resource sharing](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS)
and worker policies. `bundle_status` reports packaged frontend loading.

[Native queries, models, and results](runtime.md) are available with the
headless extra. The base install includes widgets and agent guidance. Browser-backed sources
compile and execute in the browser.

Set `auto_run=False` to require an explicit **Check** or **Run**
action. PyMalloy values displayed directly as cell outputs use this setting.
Check resolves the model and schemas, which can read data for schema discovery.
A native `Model` or `Query` offers **Preview** using its existing
connection using the model's timeout, inherited from its connection unless
overridden. Materialized `Result` values show up to
20 retained rows. See [notebook editing](../guide/notebook-editing.md) for the
behavior of each value type.

For native `Model`, `Query`, and `Result` values, omit `files` and `runtime`:
their Python context supplies data access. A widget bound to a `Query` accepts
that query's name or `None`. Pass its `Model` to choose among the model's queries.

A `Draft` can carry `pm.data(frame)` inputs. MalloyWidget sends their captured
[Parquet](https://parquet.apache.org/docs/) columnar-file bytes as managed virtual files when compilation or execution is requested. This requires [PyArrow](https://arrow.apache.org/docs/python/), the Python
columnar-data library, installed directly or through the headless extra. User `files` cannot shadow managed names. See the
[dataframe guide](../guide/dataframes.md).

## Validation and lifecycle

Invalid widget inputs raise `traitlets.TraitError`. Widget givens accept finite
JSON-compatible values, including exact Python integers, and reject Python
`Decimal`, `date`, and `datetime` objects. Convert them to representations matching
the model's declared types before assignment.

Construction with `auto_run=True` materializes captured inputs. With `False`,
materialization waits for Check or Run. Attaching a browser view starts requested
execution. Assignments after `close()` are rejected. Closing releases attached
browser resources and publishes `status="closed"`. Retained snapshots remain
readable. A native model or query supplies its own connection name and remains
caller-owned.

Source identity and captured imports use [`ModelSource`](runtime.md#modelsource).
