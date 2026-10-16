# Author and validate a model

Compose [Malloy](https://docs.malloydata.dev/) sources and views as immutable Python
values. Validate the model against [DuckDB](https://duckdb.org/docs/stable/), an
embedded SQL engine, and save an accepted revision.

```python
from pathlib import Path
from tempfile import TemporaryDirectory

import pymalloy as pm

orders = (
    pm.sql("SELECT * FROM (VALUES (1, 20), (2, 22)) t(id, amount)")
    .primary_key("id")
    .dimension(doubled=pm.col("amount") * 2)
    .measure(revenue=pm.col("amount").sum().doc("Booked amount in USD."))
    .view(totals=pm.view().aggregate("revenue").doc("Total booked amount."))
    .doc("One row per order. Amount is USD.")
)
candidate = pm.draft().sources(orders=orders)
checks = {
    "unique_id": pm.source("orders").pipe(
        pm.view().group_by("id").aggregate(n=pm.count()).having(pm.col("n") > 1)
    ),
    "non_null_id": pm.source("orders").pipe(
        pm.view().where(pm.col("id").is_null()).select("id")
    ),
}
with pm.connect() as con:
    accepted = con.validate(candidate, checks).require_valid()
    print([(check.name, check.status) for check in accepted.checks])
with TemporaryDirectory() as directory:
    path = accepted.save(Path(directory) / "orders.malloy")
    assert path.read_text() == candidate.text
```

Both checks return zero counterexamples:

```text
[('unique_id', 'passed'), ('non_null_id', 'passed')]
```

`dimension` defines row-level fields. `measure` defines reusable aggregates.
`primary_key` declares row identity. Test uniqueness and nulls before relying on
that declaration. `view` binds a source-relative query stage.
Declaration methods merge into one trailing `extend` block.

## Field paths and scalar expressions

Positional strings in `group_by`, `aggregate`, and `select` name field paths,
split on dots. `select("customer.name")` means
`select(pm.col("customer", "name"))`. `order_by` strings name single output
columns, so follow `group_by("customer.name")` with `order_by("name")`.
A dotted `order_by` string raises `ValueError`.

Keyword values require `Expr`. `pm.col("customer.name")` names a single field
containing a literal dot. Strings beside expressions are literal values:
`pm.col("region") == "North"` compares a field to text.

Use arithmetic and comparisons to compose expressions. Combine predicates with
`&`, `|`, and `~`, and parenthesize each comparison. Python `and`, `or`, truth
testing, and chained comparisons raise `TypeError`. `expr.str.lower()` normalizes
text. `expr.dt.year()` extracts a year, while `expr.dt.truncate("month")`
retains a complete month including its year. See the
[expression reference](../reference/authoring.md#scalar-expressions).

## Join sources and nest results

```python
import pymalloy as pm

labels = pm.sql("SELECT 1 AS id, 'North' AS region").primary_key("id")
orders = (
    pm.sql("SELECT * FROM (VALUES (1, 20), (1, 22)) t(label_id, amount)")
    .join_one("label", labels, on=pm.col("label_id") == pm.col("label", "id"))
    .measure(revenue=pm.col("amount").sum())
)
regional = (
    pm.view()
    .group_by("label.region")
    .aggregate("revenue")
    .nest(amounts=pm.view().select("amount").order_by("amount"))
    .order_by("region")
)
with pm.connect() as con:
    result = con.model(pm.draft().queries(report=orders.pipe(regional))).query().run()
print(result.to_pylist())
```

The result contains region `North`, revenue `42`, and nested amounts `20` and `22`.
`join_one` declares at most one target row per source row. Use `join_many` for
multiple targets or `join_cross` for a cross product, optionally with `on=`.
Check target keys, unmatched source keys, and totals before and after a join.
A compiling relationship still needs data evidence and review.

`nest` also accepts saved-view names. Its output has its own grain and ordering.

## Rename, calculate, and refine views

```python
import pymalloy as pm
from pymalloy.expressions import call

orders = (
    pm.sql("SELECT * FROM (VALUES ('North', 20), ('South', 30)) t(region, amount)")
    .rename(booked="amount")
    .view(by_region=pm.view().group_by("region").aggregate(revenue=pm.col("booked").sum()))
)
stage = pm.view("by_region").order_by("region").calculate(
    prior=call("lag", pm.col("revenue"))
)
query = orders.pipe(stage).pipe(pm.view().select("region", "prior").order_by("region"))
with pm.connect() as con:
    rows = con.model(pm.draft().queries(report=query)).query().run().to_pylist()
print(rows)
```

Expected output:

```text
[{'region': 'North', 'prior': None}, {'region': 'South', 'prior': Decimal('20')}]
```

`rename(booked="amount")` maps the new field name to the existing name.
`calculate` adds window values against the current stage's output and ordering.
`pm.view("by_region")` references a saved view. Chained clauses refine it with
Malloy's `+` syntax. `pipe` starts a subsequent stage. A string passed to `pipe`
selects a saved view directly.

## Annotate and extend the grammar

`.doc(text)` attaches Malloy's native description route to a named binding.
Use `.annotate("bar_chart")` for a renderer tag or
`.annotate("unit=USD", route="business")` for application metadata.
Bind an annotated view with `source.view(name=stage)` before using it in a
pipeline. Annotate a complete query before binding it with `draft.queries`.

`Expr.raw(code)`, `Source.raw(*parts)`, and `View.raw(*parts)` accept trusted Malloy
syntax. `Draft.append(*parts)` appends complete declarations. Include the spaces
and punctuation needed between raw parts. Use `pm.read_model(text)` when
handwritten syntax needs [named editing slots](editing.md).

## Validate and persist

`con.check(candidate)` returns diagnostics and schema metadata.
`con.validate(candidate, checks)` compiles once and executes named counterexample
queries under one deadline. Zero rows passes. A failed check retains one row.
Validation captures givens once and closes its model before returning.

Pass `documentation=DocumentationPolicy()` from `pymalloy.validation` to check
source, measure, and view descriptions. Warnings are advisory.
`accepted.require_valid(warnings_as_errors=True)` makes warnings blocking too.

`Draft.save` writes unfinished source. `Validation.save` requires accepted
evidence and writes that captured revision. Use [bundles](bundles.md) for
captured Python data and copied inputs. See [concepts](concepts.md#what-checks-establish)
for the evidence each check establishes and [persistence](../reference/authoring.md#persistence)
for file conflict and relocation rules.
