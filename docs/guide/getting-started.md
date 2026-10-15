# Run your first Python query

Install PyMalloy with native execution and [Polars](https://docs.pola.rs/), a
columnar dataframe library. Use Python 3.12 or newer.

```sh
pip install 'pymalloy[headless]' polars
```

[Malloy](https://docs.malloydata.dev/) compiles a semantic model to SQL.
[DuckDB](https://duckdb.org/docs/stable/), an embedded database engine, runs it.
The `headless` extra supplies both DuckDB and [Deno](https://docs.deno.com/),
the JavaScript runtime hosting the Malloy compiler.

## Author and run

```python
import pymalloy as pm

orders = pm.sql(
    "SELECT * FROM (VALUES ('North', 20), ('North', 22), ('South', 30)) t(region, amount)"
)
model = (
    pm.draft()
    .sources(
        orders=orders.measure(
            revenue=pm.col("amount").sum().doc("Booked amount in USD.")
        )
    )
    .queries(
        by_region=pm.source("orders").pipe(
            pm.view().group_by("region").aggregate("revenue").order_by("region")
        )
    )
)
with pm.connect() as con:
    result = con.model(model).query("by_region").run()
    print(result.to_polars())
```

Expected output:

```text
shape: (2, 2)
┌────────┬───────────────┐
│ region ┆ revenue       │
│ ---    ┆ ---           │
│ str    ┆ decimal[38,0] │
╞════════╪═══════════════╡
│ North  ┆ 42            │
│ South  ┆ 30            │
└────────┴───────────────┘
```

`orders` is a source with a reusable `revenue` measure. The draft names that
source and a `by_region` query. `con.model(model)` compiles the draft,
`query("by_region")` selects the query, and `run()` materializes its result.
The connection closes its models and database on exit. The result stays readable.

Use `model.text` to inspect the generated Malloy. Continue with
[authoring](authoring.md), [editing an existing file](editing.md), or
[query selection and runtime lifetime](running.md).
