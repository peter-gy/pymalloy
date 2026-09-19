# Connect files, tables, and Python data

Choose how a model accesses its inputs:

| Input                              | Lifetime and use                                                      |
| ---------------------------------- | --------------------------------------------------------------------- |
| `pm.data(frame, name="orders")`    | Immutable captured values for composition, widgets, and bundles       |
| `pm.table("orders")`               | A catalog table or registered object on the model's DuckDB connection |
| `pm.table(Path("orders.parquet"))` | A file resolved by DuckDB                                             |
| Widget `files={...}`               | Bytes or URLs registered as virtual files in the browser              |

Install `pymalloy[headless]` and `polars` to query a captured Polars dataframe:

```python
import polars as pl
import pymalloy as pm

orders = pl.DataFrame({"region": ["North", "South"], "amount": [42, 30]})
model = pm.draft().define(orders=pm.data(orders)).queries(
    totals=pm.ref("orders").pipe(pm.query(
        pm.group_by(pm.col("region")),
        pm.aggregate(total=pm.col("amount").sum()),
        pm.order_by(pm.col("region")),
    ))
)
print(pm.run(model).rows())
```

The captured input stays fixed when the original dataframe changes. DuckDB
resolves catalog names, quoted identifiers, CTEs, reader functions, and file paths.
Schema discovery and execution use the same connection and settings.

Owned connections default to UTC and configure `file_search_path` from `data_root`
(Python) or `dataRoot` (Node), defaulting to the current directory at creation.
The current process directory has precedence over that search path. Absolute
paths provide an unambiguous file identity.

Pass native DuckDB settings through `config`, for example `config={"threads": 2}`.
Settings apply before schema discovery and execution. Explicit `timezone` and
`file_search_path` settings are preserved. Choose either `data_root` or a configured
`file_search_path`. Supplying both raises an error.

Use `extensions=("httpfs",)` to install and load native DuckDB extensions before
compilation. Installation may download from DuckDB's configured repository.
Extension initialization counts toward the model or check call's timeout.

A model's URL controls imports independently of data access. Loading a file does
not change the connection's data search path.

## Borrow a connection

Register Python objects with DuckDB directly when you want native registration
and caller-controlled lifetime:

```python
import duckdb
import polars as pl
import pymalloy as pm

orders = pl.DataFrame({"amount": [42, 30]})
with duckdb.connect() as connection:
    connection.register("orders", orders)
    result = pm.run(
        "run: duckdb.table('orders') -> { aggregate: total is amount.sum() }",
        connection=connection,
    )
    print(result.rows())  # [{'total': Decimal('72')}]
    connection.unregister("orders")
```

Configure borrowed connections yourself. Supplying `data_root`, `database`,
`config`, a nonempty `extensions` list, or `read_only` with a borrowed connection
raises an error. Model cleanup preserves
the connection, settings, registrations, and transaction state. Coordinate direct
connection use with model operations. A timed-out query interrupts its statement
and leaves a healthy model reusable. If DuckDB aborts an explicit transaction,
the caller must roll it back before issuing another statement.

Python adapters use the Malloy connection name `duckdb` by default. Match a
model's alternative name with `connection_name="analytics"` on `pm.model` or
`pm.check` and `connection="analytics"` on `pm.table`, `pm.sql`, or `pm.data`.
The native engine remains DuckDB.

Browser models receive virtual files with `files`. Each model snapshots its
mapping. URL descriptors require HTTP(S) and server CORS permission. COPY output
paths in native DuckDB follow DuckDB's rules. Notebook exporters anchor relative
COPY destinations to their exported data root.

Follow [capture Python data](dataframes.md) when an input must travel with the
model, or [bundle models and inputs](bundles.md) to publish explicitly bound files.
