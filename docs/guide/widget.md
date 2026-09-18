# Update widget inputs and read results

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

Assign `source`, `query`, `givens`, or `files` to request another result.
`files` maps virtual names to UTF-8 text, bytes, or HTTP(S) URL descriptors.
Remote servers must allow CORS. A `ModelSource` can replace source text.

`widget.state` is a detached snapshot with `status`, typed query descriptors,
SQL, columns, rows, the Malloy result tree, diagnostics, and an error message.
Observe `state` to react to asynchronous results. Read `rows` when status is
`ready`. Python bigint and nested values are exact. Decimal text becomes Decimal.

Every result belongs to an input revision. A result from earlier work cannot
replace a newer input's state. Mutating a returned snapshot does not update the
widget. Assign a complete input mapping and call `widget.close()` when finished.
