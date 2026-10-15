# Python authoring patterns

Construct [Malloy](https://docs.malloydata.dev/) syntax with immutable `Source`,
`View`, `Expr`, and `Draft` values:

```python
import pymalloy as pm

orders = (
    pm.sql("SELECT * FROM (VALUES ('North', 20), ('North', 22)) t(region, amount)")
    .measure(revenue=pm.col("amount").sum().doc("Booked amount in USD."))
    .view(by_region=pm.view().group_by("region").aggregate("revenue"))
)
candidate = pm.draft().sources(orders=orders).queries(
    report=pm.source("orders").pipe(pm.view("by_region").order_by("region"))
)
with pm.connect() as con:
    print(con.model(candidate).query("report").run().to_pylist())
```

The result is North revenue `42`. Source methods declare dimensions, measures,
renames, keys, joins, and saved views. View methods group, aggregate, select,
filter, nest, order, limit, and calculate window values. `pipe` starts another
stage. `pm.view(name)` references a saved view for refinement.

Positional strings in `group_by`, `aggregate`, and `select` name field paths split
on dots. `order_by` strings name single output columns. Keyword values require
`Expr`. `pm.col("customer", "name")` is a path. `pm.col("customer.name")` is one
identifier with a literal dot. Strings beside expressions remain literal values.
Combine comparisons with parenthesized `&`, `|`, and `~` predicates.

`pm.read_model` preserves source while exposing named editing scopes. Select a
nested view or join before replacing its fields. Missing names raise `KeyError`
and ambiguous names raise `ValueError`. `.doc` updates an owned description
route. Unspecified annotation routes and shared statement annotations stay intact.

`model.source()` captures imports and `pm.data` input owners in `ModelSource`.
Compile that snapshot independently of the original model. Live imports added
with `draft.include(url)` precede their consumers. Closed snapshots require every
import in their mapping.

`draft.to_python(name="candidate", inputs={...})` emits executable constructors.
Captured input bindings name trusted Python expressions supplying prepared data.
Supported scalars render canonically. Other grammar remains in `Expr.raw`,
`Source.raw`, `View.raw`, or `Draft.append`. Recheck semantics after editing emitted
code. Read and save an unchanged file for exact byte preservation.

Use `model.query(name)` for inventory selection,
`model.query(pm.source("orders").pipe(stage))` for composed queries, and
`model.query(malloy="run: orders -> ...")` for native query text.
`Result.to_pylist`, `to_arrow`, `to_polars`, and Arrow stream consumers read the
materialized result. They never rerun SQL.
