# Run queries from Python

Use a native session to run Malloy in a script, service, or notebook and receive
a Polars dataframe. Install the native dependencies:

```sh
pip install "pymalloy[server]"
```

## Run a query

```python
from pymalloy.server import Session

with Session() as session:
    result = session.run("""
        run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }
    """)

assert result.item() == 42
```

`run()` compiles Malloy to SQL and executes it. Results are **materialized**: all
rows are in Python memory and remain available after the session closes.
The `with` block closes the session even on failure.

The compiler runs in Deno, a JavaScript runtime included with the `server` extra
and started on first use. DuckDB executes queries in Python.

## Query Python data

Register a dataframe on the session's connection:

```python
import polars as pl
from pymalloy.server import Session

with Session() as session:
    session.connection.register(
        "orders", pl.DataFrame({"region": ["North", "South", "North"], "amount": [40, 30, 2]})
    )
    result = session.run("""
        run: duckdb.table('orders') -> {
          group_by: region
          aggregate: total is amount.sum()
          order_by: total desc
        }
    """)

assert result.to_dicts() == [
    {"region": "North", "total": 42},
    {"region": "South", "total": 30},
]
```

Load trusted models: schema discovery accesses their data before queries run.
See [data and connections](/guide/data) for files, databases, and borrowed connections.

## Reuse an analysis

Use `session.model(source)` to retain definitions or `session.load(path)` to
load a `.malloy`, `.malloynb`, or `.malloysql` file. Read `model.queries` to
discover query selectors, then call `model.run(query=...)`.

See [reusable models](/guide/models) and the [native Python API](/reference/server).
