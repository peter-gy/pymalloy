# Author and verify models

Compose Malloy sources in Python, edit existing models by name, and test their
assumptions before saving. Construction works with the base package. Install
`pymalloy[server]` to read existing models, check them, and execute queries.

```python
import pymalloy as pm

orders = (
    pm.sql(
        "SELECT * FROM (VALUES (1, 40, 'North'), (2, 2, 'North')) t(id, amount, region)"
    )
    .extend(
        pm.primary_key("id"),
        pm.measure(revenue=pm.col("amount").sum().doc("Gross order revenue in USD.")),
        pm.view(
            by_region=pm.query(
                pm.group_by(pm.col("region")),
                pm.aggregate(pm.col("revenue")),
                pm.order_by(pm.col("revenue").desc(), pm.col("region")),
            ).doc("Revenue by region with stable ranking.")
        ),
    )
    .doc("One row per order, with amounts in USD.")
)

candidate = pm.draft().define(orders=orders)
report = candidate.validate(
    {
        "unique_order_id": pm.ref("orders").pipe(
            pm.query(
                pm.group_by(pm.col("id")),
                pm.aggregate(n=pm.count()),
                pm.having(pm.col("n") > 1),
            )
        ),
        "non_null_order_id": pm.ref("orders").pipe(
            pm.query(pm.where(pm.col("id").is_null()), pm.select(pm.col("id")))
        ),
        "known_total": pm.ref("orders").pipe(
            pm.query(
                pm.aggregate(pm.col("revenue")), pm.having(pm.col("revenue") != 42)
            )
        ),
    }
)
report.save("orders.malloy", warnings_as_errors=True)
```

Source expressions and clauses are immutable values. Reuse them across drafts.
`define(orders=...)` names the source, while `measure(revenue=...)` names a field.
Use `pm.col("amount")` for a column and `pm.lit("North")` for a literal.
Arithmetic and comparisons build symbolic expressions, checked by Malloy.

Each validation query returns counterexamples. Zero rows passes. A failed check
retains one example in `report.checks[i].result.rows()`. Compilation or query errors
also make `report.ok` false. Validation compiles once, shares one timeout budget
across its phases, and closes its owned model before returning.

## Compose scalar expressions

```python
amount = pm.col("amount")
predicate = (amount > 0) & (pm.col("region") == "North")
source = pm.table("orders.parquet").extend(
    pm.dimension(
        normalized_region=pm.col("region").str.lower(),
        order_year=pm.col("created_at").dt.year(),
        order_month=pm.col("created_at").dt.truncate("month"),
    ),
    pm.measure(revenue=amount.sum()),
    pm.where(predicate),
)
```

Python values beside an `Expr` become literals. `pm.col("labels", "region")`
refers to a joined field. `pm.given("minimum")` refers to a declared given.
Use `&`, `|`, and `~` with parenthesized comparisons for predicates. Python
`and`, `or`, and chained comparisons require a truth value and raise an error.

`pm.raw_expr("...")` embeds scalar syntax outside the symbolic API.
`pm.syntax("...")` embeds source or query clauses. Keep those boundaries explicit
so an ordinary Python string cannot accidentally become executable Malloy.

## Ground definitions in data

Use `pm.table("orders.parquet")` with `candidate.compile(data_root="data")` for
files. A `Path` table argument explicitly denotes a file and quotes its path.
Inspect real fields and values before choosing keys, measures, or joins:

```python
model = candidate.compile()
try:
    print(model.inspect().model.sources)
    print(model.query("orders.by_region").preview(limit=5).rows())
finally:
    model.close()
```

`preview` bounds returned rows, with a default of 20. Aggregation may still scan
the full input, and nested values may contain more rows. Pass `timeout=` to bound
operation time. COPY statements are rejected.

Check key uniqueness and nulls separately. Check target uniqueness before choosing
`pm.join(..., kind="one")`, and compare totals before and after joins. Compilation
establishes language validity. Data checks and review establish the intended
meaning of a metric.

## Edit existing models

`read_model` uses Malloy's parser to expose named source, query, field, and explicit
join expressions while retaining the original text:

```python
from pathlib import Path

original = pm.read_model(Path("orders.malloy"))
candidate = original.define(
    orders=original["orders"].replace(
        revenue=pm.col("amount").avg().doc("Mean order amount in USD.")
    )
)
print(candidate.diff())
print(candidate.check().diagnostics)
```

The edit replaces `revenue` and its directly attached `#(doc)` description. It
preserves the surrounding text and leaves `original` unchanged. A replacement
without `.doc(...)` retains the existing description. Shared statement tags and
block annotations remain unchanged. Names belong to their containing
scope. A nested view's fields require selecting that view first. Missing names
raise `KeyError`, and ambiguous names raise `ValueError`.

Changing a measure also requires reviewing its name, documentation, and assertions.
For a separate definition, derive a source with `pm.ref`:

```python
candidate = original.define(
    north_orders=pm.ref("orders")
    .extend(pm.where(pm.col("region") == "North"))
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

The emitted Python uses scalar constructors such as `pm.col`, `pm.lit`, and
operators inside the model syntax. Editing those operations changes the resulting
Malloy. Supported scalar expressions may be respelled with quoted identifiers and
explicit parentheses. Their semantics, source identity, and captured imports are
preserved. Comments and other surrounding syntax retain their original text.

Reading a file and saving it unchanged preserves its exact bytes. A Python
roundtrip preserves meaning rather than scalar spelling. Rerun relevant queries
and assertions after editing the generated Python.
`read_model` accepts plain `.malloy` sources. Notebook documents remain available
through the execution and export APIs.

## Check and save a revision

| Operation                | Result                                                                                              |
| ------------------------ | --------------------------------------------------------------------------------------------------- |
| `draft.check()`          | Compiler diagnostics and advisory documentation warnings, source fields, query names, and locations |
| `draft.validate(checks)` | Static diagnostics and executable assertions for the captured revision                              |
| `draft.compile()`        | A reusable model for inspection and execution                                                       |

Documentation checks flag missing source, measure, and view descriptions.
Warnings remain advisory unless `warnings_as_errors=True` is passed to
`Validation.require_valid()` or `Validation.save()`.

`Draft.save()` saves unfinished work. `Validation.save()` requires successful
validation and saves the captured revision. Both reject an unrelated existing
file unless `overwrite=True`. Loaded files reject external changes. Reload after
saving before making another revision.

Validated saves with captured imports require the original root directory and
unchanged imported files. To relocate a model, save the draft and revalidate at
its destination. Saving writes the root file. Data may change after validation,
so retain and rerun the assertions.

## Agent instructions

```python
import pymalloy.agent as agent

print(agent.agent_skill().body)
print(agent.agent_skill().file("references/modeling.md").read_text())
```

Installed instructions match the package version. Marimo discovers
`pymalloy.agent` through its capability entry point. See the
[authoring reference](../reference/authoring.md) for all constructors and methods.
