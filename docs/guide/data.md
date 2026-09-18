# Connect files, tables, and Python data

Pass Python data as named tables:

```python
import polars as pl
import pymalloy as pm

orders = pl.DataFrame({"region": ["North", "South"], "amount": [42, 30]})
result = pm.run(
    "run: duckdb.table('orders') -> { group_by: region aggregate: total is amount.sum() }",
    tables={"orders": orders},
)
print(result.rows())
```

`pm.model` accepts the same `tables` mapping for repeated queries. DuckDB resolves
catalog names, quoted identifiers, CTEs, reader functions, and file paths.
Schema discovery and execution use the same connection and settings.

Owned connections set UTC and configure `file_search_path` from `data_root`
(Python) or `dataRoot` (Node), defaulting to the current directory at creation.
The current process directory has precedence over that search path. Absolute
paths provide an unambiguous file identity.

A model's URL controls imports independently of data access. Loading a file does
not change the connection's data search path.

## Borrow a connection

```python
import duckdb
import pymalloy as pm

connection = duckdb.connect()
connection.execute("SET file_search_path = 'examples'")
result = pm.run(
    "run: duckdb.table('orders.csv') -> { aggregate: total is amount.sum() }",
    connection=connection,
)
print(connection.execute("SELECT 1").fetchone())
connection.close()
```

Configure borrowed connections yourself. Supplying `data_root`, `database`, or
`read_only` with a borrowed connection raises an error. Caller ownership,
settings, and transactions survive model cleanup. Registering `tables` changes
the supplied connection. Coordinate direct connection use with model operations.

Browser models receive virtual files with `files`. Each model snapshots its
mapping. URL descriptors require HTTP(S) and server CORS permission. COPY output
paths in native DuckDB follow DuckDB's rules. Notebook exporters anchor relative
COPY destinations to their exported data root.
