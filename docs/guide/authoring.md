# Author and validate models

Compose Malloy sources in Python, edit existing models by name, and test their
assumptions before saving. Construction works with the base package. Install
`pymalloy[headless]` to read existing models, check them, and execute queries.

```python
import pymalloy as pm

orders = (
    pm.sql(
        "SELECT * FROM (VALUES (1, 40, 'North'), (2, 2, 'North')) t(id, amount, region)"
    )
    .primary_key("id")
    .measure(revenue=pm.col("amount").sum().doc("Gross order revenue in USD."))
    .view(
        by_region=pm.view()
        .group_by(pm.col("region"))
        .aggregate(pm.col("revenue"))
        .order_by(pm.col("revenue").desc(), pm.col("region"))
        .doc("Revenue by region with stable ranking.")
    )
    .doc("One row per order, with amounts in USD.")
)

candidate = pm.draft().sources(orders=orders)
report = pm.connect().validate(
    candidate,
    {
        "unique_order_id": pm.source("orders").pipe(
            pm.view()
            .group_by(pm.col("id"))
            .aggregate(n=pm.count())
            .having(pm.col("n") > 1)
        ),
        "non_null_order_id": pm.source("orders").pipe(
            pm.view().where(pm.col("id").is_null()).select(pm.col("id"))
        ),
        "known_total": pm.source("orders").pipe(
            pm.view().aggregate(pm.col("revenue")).having(pm.col("revenue") != 42)
        ),
    },
)
report.save("orders.malloy", warnings_as_errors=True)
```

The assertions check duplicate keys, null keys, and a known total. A zero-row
result passes. The save publishes the accepted root source. See
[concepts and boundaries](concepts.md#what-checks-establish) for the scope of this evidence.

Sources and views are immutable values. Reuse them across drafts.
`sources(orders=...)` names the source, while `measure(revenue=...)` names a field.
Use `pm.col("amount")` for a column and `pm.lit("North")` for a literal.
Arithmetic and comparisons build symbolic expressions, checked by Malloy.

Positional strings in `group_by`, `aggregate`, and `select` name field paths
split on dots. `view.select("customer.name")` means
`view.select(pm.col("customer", "name"))`. Keyword values require `Expr`.
`pm.col("customer.name")` names a field containing a literal dot. Strings beside
expressions remain literal values. `order_by` strings name output columns, so
follow `group_by("customer.name")` with `order_by("name")`. Dotted `order_by`
strings raise `ValueError`.

Each validation query returns counterexamples. Zero rows passes. A failed check
retains one example in `report.checks[i].result.to_pylist()`. Compilation or query errors
also make `report.ok` false. Validation compiles once, shares one timeout budget
across its phases, and closes its owned model before returning.

## Compose scalar expressions

```python
amount = pm.col("amount")
predicate = (amount > 0) & (pm.col("region") == "North")
source = (
    pm.table("orders.parquet")
    .dimension(
        normalized_region=pm.col("region").str.lower(),
        order_year=pm.col("created_at").dt.year(),
        order_month=pm.col("created_at").dt.truncate("month"),
    )
    .measure(revenue=amount.sum())
    .where(predicate)
)
```

Python values beside an `Expr` become literals. `pm.col("labels", "region")`
refers to a joined field. `pm.given("minimum")` refers to a declared given.
Use `&`, `|`, and `~` with parenthesized comparisons for predicates. Python
`and`, `or`, and chained comparisons require a truth value and raise an error.

`pm.Expr.raw("...")` embeds scalar syntax outside the symbolic API.
`pm.Source.raw("...")` embeds relation syntax, and `pm.View.raw("...")` embeds query stages. Keep those boundaries explicit
so an ordinary Python string cannot accidentally become executable Malloy.

## Ground definitions in data

Use `pm.table("orders.parquet")` with `pm.connect(data_root="data").model(candidate)` for
files. A `Path` table argument explicitly denotes a file and quotes its path.
Inspect real fields and values before choosing keys, measures, or joins:

```python
model = pm.connect().model(candidate)
try:
    print(model.inspect().model.sources)
    print(model.query("orders.by_region").preview(limit=5).to_pylist())
finally:
    model.close()
```

`preview` bounds returned rows, with a default of 20. Aggregation may still scan
the full input, and nested values may contain more rows. Pass `timeout=` to bound
operation time. COPY statements are rejected.

Check key uniqueness and nulls separately. Check target uniqueness before choosing
`source.join_one(...)`, and compare totals before and after joins. Compilation
establishes language validity. Data checks and review establish the intended
meaning of a metric.

## Edit existing models

`read_model` uses Malloy's parser to expose named source, query, field, and explicit
join expressions while retaining the original text:

```python
from pathlib import Path

original = pm.read_model(Path("orders.malloy"))
candidate = original.sources(
    orders=original["orders"].replace(
        revenue=pm.col("amount").avg().doc("Mean order amount in USD.")
    )
)
print(candidate.diff())
print(pm.connect().check(candidate).diagnostics)
```

The edit replaces `revenue` and its directly owned documentation route. It
preserves the surrounding text and leaves `original` unchanged. A replacement
without `.doc(...)` retains the existing description. `.annotate(text, route=...)`
replaces another owned route, such as a renderer tag or app annotation. Shared
statement annotations remain unchanged. Names belong to their containing
scope. A nested view's fields require selecting that view first. Missing names
raise `KeyError`, and ambiguous names raise `ValueError`.

Attach renderer and application annotations with their native routes:

```python
view = pm.view().aggregate(revenue=pm.col("amount").sum()).annotate("bar_chart")
measure = pm.col("amount").sum().annotate("unit=USD", route="research")
```

Changing a measure also requires reviewing its name, documentation, and assertions.
For a separate definition, derive a source with `pm.source`:

```python
candidate = original.sources(
    north_orders=pm.source("orders")
    .where(pm.col("region") == "North")
    .doc("Orders in the North region.")
)
```

`pm.read_model(model.source())` branches a compiled model's captured imports.
`.include("base.malloy")` adds a live import relative to the draft's URL.
`pm.draft(text)` composes text verbatim. Use `pm.read_model(text)` when that text
needs named editing slots.

## Roundtrip through Python

```python
python = original.to_python(name="candidate")
namespace = {}
exec(python, namespace)
restored = namespace["candidate"]
assert restored["orders"]["revenue"].equals(original["orders"]["revenue"])
```

The emitted Python uses source and query constructors where the parsed structure
can be represented, with `pm.col`, `pm.lit`, and operators for scalar expressions.
Unrepresented grammar and surrounding comments remain explicit syntax fragments. Editing those operations changes the resulting
Malloy. Constructors indent nested blocks and quote names when Malloy requires
it. Supported scalar expressions may gain explicit parentheses. Their semantics, source identity, and captured imports are
preserved. Comments and other surrounding syntax retain their original text.

Reading a file and saving it unchanged preserves its exact bytes. A Python
roundtrip preserves meaning rather than scalar spelling. Rerun relevant queries
and assertions after editing the generated Python.
`read_model` accepts plain `.malloy` sources. Notebook documents remain available
through the execution and export APIs.

## Check and save a revision

| Operation                            | Result                                                                 |
| ------------------------------------ | ---------------------------------------------------------------------- |
| `connection.check(draft)`            | Compiler diagnostics, source fields, query names, and locations        |
| `connection.validate(draft, checks)` | Static diagnostics and executable assertions for the captured revision |
| `connection.model(draft)`            | A reusable model for inspection and execution                          |

Enable documentation checks explicitly:

```python
from pymalloy.validation import DocumentationPolicy

report = pm.connect().check(candidate, documentation=DocumentationPolicy())
```

The default policy checks source, measure, and view descriptions. Pass the same
`documentation=` option to `validate` when descriptions are an acceptance
condition. Warnings remain advisory unless `warnings_as_errors=True` is passed to
`Validation.require_valid()` or `Validation.save()`.

Choose what to publish:

- `Draft.save()` writes unfinished root source.
- `Validation.save()` writes the accepted root revision after checking validity.
- [`bundle(accepted, ...)`](bundles.md) writes source, imports, and declared or
  captured inputs into a new directory.

Plain saves reject managed dataframe inputs. Loaded files reject observed
external changes, and validated saves also check imported files and the root
directory. Reload after saving before editing again. The
[persistence reference](../reference/authoring.md#persistence) defines overwrite
and relocation rules.

## Agent instructions

The base package includes versioned model-authoring guidance:

```python
import pymalloy.agent as agent

print(agent.agent_skill().body)
print(agent.agent_skill().file("references/modeling.md").read_text())
```

Installed instructions match the package version. Marimo discovers
`pymalloy.agent` through its capability entry point. See the
[authoring reference](../reference/authoring.md) for all constructors and methods.
