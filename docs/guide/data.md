# Connect files and catalog tables

`pm.table` references a table or file through [DuckDB](https://duckdb.org/docs/stable/),
the native SQL engine. Schema discovery and execution use the same connection
and settings. This example writes its data in a temporary directory:

```python
from pathlib import Path
from tempfile import TemporaryDirectory

import pymalloy as pm

with TemporaryDirectory() as directory:
    path = Path(directory) / "orders.csv"
    path.write_text("region,amount\nNorth,20\nNorth,22\n")
    candidate = pm.draft().queries(
        total=pm.table(path).pipe(pm.view().aggregate(total=pm.col("amount").sum()))
    )
    with pm.connect(data_root=directory) as con:
        print(con.model(candidate).query().run().to_pylist())
```

Expected output is `[{'total': Decimal('42')}]`.
Use [`pm.data(frame)`](dataframes.md) when prepared Python values must travel
with a model, or [widget virtual files](widget.md) for browser data.

## Resolve names and paths

| Input                          | Resolution                                                                         |
| ------------------------------ | ---------------------------------------------------------------------------------- |
| `pm.table("orders")`           | Native catalog table or registered object, then DuckDB file resolution             |
| `pm.table("orders.csv")`       | DuckDB table/file reference retaining the supplied relative spelling               |
| `pm.table(Path("orders.csv"))` | Absolute file reference, resolved when constructed                                 |
| `pm.sql(text)`                 | Native SQL including catalog names, common table expressions, and reader functions |

[Malloy](https://docs.malloydata.dev/), the model compiler, delegates schemas
to the configured connection. DuckDB resolves identifiers with its native quoting
and catalog rules. The current working directory takes precedence over
`file_search_path`. Use absolute file paths to disambiguate duplicate filenames.

Owned connections set UTC and `file_search_path` at creation. `data_root` defaults
to the current directory. `config={"threads": 2}` supplies native settings.
Explicit `timezone` and `file_search_path` values are preserved. Choose either
`data_root` or a configured `file_search_path`. Supplying both raises `ValueError`.

The model's URL determines import resolution independently of data paths.
Loading a model file keeps the connection's search path.
[Borrowed connections](running.md#borrow-a-duckdb-connection) use caller settings.

## Use remote files and extensions

Pass `extensions=("httpfs",)` to install and load DuckDB's
[HTTP and object-storage extension](https://duckdb.org/docs/stable/core_extensions/httpfs/overview.html)
before compilation. Installation can download from the configured extension
repository and consumes the connection-opening timeout. Remote data access needs
network permission in the execution environment.

`pm.table("https://example.org/orders.parquet")` is a remote file reference.
Use an actual reachable dataset URL. Remote values remain live unless you copy
them into a captured input or bind a local copy when bundling.

Match an alternative Malloy connection name across constructors and runtime:
`pm.table("orders", connection="analytics")` uses
`pm.connect(name="analytics")`. The engine remains DuckDB.
Browser URL descriptors require cross-origin resource sharing (CORS) permission
from the server. See [notebook export](export.md) for declared SQL-reader files
and export-specific access restrictions.
