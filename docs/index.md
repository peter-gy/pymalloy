---
layout: home
hero:
  name: PyMalloy
  text: Author and run Malloy models from Python.
  tagline: Define semantic models, query with DuckDB, and share models and inputs in notebooks or source bundles.
  actions:
    - theme: brand
      text: Run your first query
      link: /guide/getting-started
    - theme: alt
      text: Show a widget
      link: /guide/widget
---

[Malloy](https://docs.malloydata.dev/) defines sources, measures, joins, and queries
and compiles them to SQL. [DuckDB](https://duckdb.org/docs/stable/) executes the SQL.
Install PyMalloy:

```sh
pip install pymalloy
```

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
print(model.text)
with pm.connect() as con:
    print(con.model(model).query("by_region").run().to_pylist())
```

The query returns North revenue `42` and South revenue `30` as exact decimal values.

## Choose a task

| Your goal                                        | Start here                                               |
| ------------------------------------------------ | -------------------------------------------------------- |
| Run your first Python query                      | [Getting started](/guide/getting-started)                |
| Reuse a model, select queries, or inspect SQL    | [Run queries from Python](/guide/running)                |
| Understand drafts, models, and captured evidence | [Concepts and boundaries](/guide/concepts)               |
| Compose sources, measures, joins, and views      | [Author a model](/guide/authoring)                       |
| Change an existing Malloy file                   | [Edit a model](/guide/editing)                           |
| Connect files or catalog tables                  | [Data access](/guide/data)                               |
| Bring prepared Python data into a model          | [Capture Python data](/guide/dataframes)                 |
| Bind typed query parameters                      | [Givens](/guide/givens)                                  |
| Display and update a notebook widget             | [Widgets](/guide/widget)                                 |
| Run Python in a browser notebook                 | [Browser Python](/guide/browser-python)                  |
| Inspect intermediate values in a notebook        | [Notebook editing](/guide/notebook-editing)              |
| Share an executable notebook                     | [Export notebooks](/guide/export)                        |
| Ship Malloy files and copied inputs              | [Source bundles](/guide/bundles)                         |
| Diagnose a failure                               | [Troubleshooting](/guide/troubleshooting)                |
| Use JavaScript                                   | [Node](/reference/node) or [browser](/reference/browser) |
| Look up an exact contract                        | [Python API](/reference/python) or [CLI](/reference/cli) |
