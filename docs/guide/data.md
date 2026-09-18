# Connect files, tables, and Python data

Use a [native Python session](/guide/native-python) to query local files, database
tables, or Python data. For browser execution, supply
[widget files](/guide/widget#files-and-imports).

Register a dataframe under a table name on the session's DuckDB connection:

```python
import polars as pl
from pymalloy.server import Session

with Session() as session:
    session.connection.register("numbers", pl.DataFrame({"value": [40, 2]}))
    result = session.run("""
        run: duckdb.table('numbers') -> {
          aggregate: total is value.sum()
        }
    """)

assert result.item() == 42
```

[PyArrow](https://arrow.apache.org/docs/python/) supplies dataframe registration.
DuckDB transfers results to Polars through Arrow's columnar format, preserving
nested values, dates, nulls, and large integers.

## Resolve data paths

`Session(data_root="examples")` resolves relative data file paths under that
directory. If omitted, the data root is the loaded file's parent or the inline
model's base directory. Absolute paths and remote URLs retain their locations.

Imports resolve independently of data files. An inline model can use
`base_dir="models"` for its imports and `data_root="data"` for its data files.
Native Python and Node model imports read local files. Remote data URLs are read
by DuckDB.

DuckDB resolves database identifiers before PyMalloy treats a name as a file.
For example, a database table named `orders.csv` takes precedence over a file
with that name. Explicit file readers such as `read_parquet('orders.parquet')`
identify file access. In native Python, their paths must be string literals or
lists of string literals so PyMalloy can bind them to the data root.

Remote data requires the appropriate DuckDB extensions, credentials, and network
access. Run trusted models, since loading a model discovers schemas by accessing
its data sources.

## Open a database

Use `Session(database="data.duckdb", read_only=True)` to query an existing database
file. Owned connections default to UTC. Configure the connection through
DuckDB's [Python API](https://duckdb.org/docs/stable/clients/python/overview).

## Borrow a connection

Pass an existing connection to retain its registrations, temporary tables,
settings, and transactions:

```python
import duckdb
from pymalloy.server import Session

with duckdb.connect() as connection:
    connection.execute("CREATE TABLE numbers AS SELECT 42 AS value")
    with Session(connection=connection) as session:
        result = session.run("""
            run: duckdb.table('numbers') -> {
              aggregate: total is value.sum()
            }
        """)
    assert connection.execute("SELECT value FROM numbers").fetchone() == (42,)

assert result.item() == 42
```

The caller owns a borrowed connection and its transactions. Coordinate direct
connection operations with session queries. After a query fails inside a
transaction, follow DuckDB's rollback requirements before using that transaction
again.

## Export data access

Save Python data to files or persistent tables before export. The notebook reads
that data when it runs, so keep paths and credentials accessible.
See [export data access](/guide/export#preserve-data-access) for connection setup
and each profile's supported inputs.
