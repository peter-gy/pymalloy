# Update widget inputs and read results

Install `pymalloy` in the notebook environment. Compilation and execution
run in the browser, so this mode needs no Deno dependency.

```python
from pymalloy import MalloyWidget

widget = MalloyWidget(
    "run: duckdb.table('orders.csv') -> { aggregate: total is amount.sum() }",
    files={"orders.csv": "amount\n20\n22\n"},
)
widget
```

Display the widget in Jupyter or marimo. The browser compiles the source and runs
DuckDB WebAssembly. Malloy's renderer displays nested results and rendering tags.
The first initialization downloads versioned WebAssembly assets.

The browser serves the `duckdb` connection by default. For source that refers to
`analytics.table(...)` or `analytics.sql(...)`, construct the widget with
`connection_name="analytics"`. This setting stays fixed for the widget's lifetime.
Captured inputs created with `pm.data(frame, connection="analytics")` use the same
explicit setting.

Assign `source`, `query`, `givens`, or `files` to request another result.
`files` maps virtual names to UTF-8 text, bytes, or HTTP(S) URL descriptors.
Remote servers must allow CORS. Source also accepts a `ModelSource` or a `Draft`,
including [captured dataframe inputs](dataframes.md#use-a-browser-without-deno).

`widget.state` is a read-only mapping containing `status`, query descriptors,
SQL, column names, rows, the Malloy result tree, diagnostics, and an error message.
Nested mappings are read-only and sequences are tuples. Observe `state` to react
to asynchronous results, and read `rows` when status is `ready`. Big integers
remain exact and decimal cells become Python `Decimal` values.

Retained snapshots stay unchanged after subsequent updates. To produce mutable
containers, convert explicitly:

```python
from pymalloy.analysis import to_dict

snapshot = to_dict(widget.state)
widget.files = {**widget.files, "orders.csv": "amount\n50\n75\n"}
```

`to_dict` preserves scalar types, including `Decimal`. Choose an encoder for those
types when serializing to JSON. `files` and `givens` also expose read-only
mappings. Assign complete mappings to publish an update.

Every result belongs to an input revision. Changing inputs cancels superseded
work, and late results cannot replace the current state. Call `widget.close()`
when finished.

If the frontend fails to load, inspect `widget.bundle_status`. The bootstrap and
JavaScript chunks come from the installed Python package through anywidget's
comm connection. `widget.state` reports compilation and query execution.
