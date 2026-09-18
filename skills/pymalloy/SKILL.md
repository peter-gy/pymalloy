---
name: pymalloy
description: Create, edit, inspect, and validate Malloy semantic models from Python. Use for model authoring, schema discovery, measures, joins, reusable queries, compiler diagnostics, documentation checks, and executable data assertions.
---

# PyMalloy model authoring

Read instructions from the installed package:

```python
import pymalloy as pm
import pymalloy.agent as agent

print(agent.agent_skill().file("references/modeling.md").read_text())
```

Syntax construction and agent discovery use the base package. Reading existing
models, checking, previews, and validation need `pymalloy[server]`. Polars and
Arrow conversion use `pymalloy[dataframes]`.

## Ground the model

If a model exists, read it and its imports first. Use
`pm.read_model(Path("orders.malloy"))` or branch a compiled snapshot with
`pm.read_model(model.source())`. Reuse definitions before adding new ones.

For a new model, start with the smallest source that exposes the data:

```python
candidate = pm.draft().define(orders=pm.table("orders.parquet"))
model = candidate.compile(data_root="data")
try:
    print(model.inspect().model.sources)
    print(model.query(malloy="run: orders -> { select: * }").preview(limit=5).rows())
finally:
    model.close()
```

Establish grain, nulls, candidate keys, units, date coverage, and join relationships
from actual fields and queries. A preview is bounded output. Use aggregate or
counterexample queries to test whole-data assumptions.

## Compose, check, verify, persist

```python
orders = (
    pm.table("orders.parquet")
    .extend(
        pm.primary_key("order_id"),
        pm.measure(revenue=pm.col("amount").sum().doc("Gross order amount in USD.")),
    )
    .doc("One row per order.")
)
candidate = pm.draft().define(orders=orders)
report = candidate.validate(
    {
        "unique_order_id": pm.ref("orders").pipe(
            pm.query(
                pm.group_by(pm.col("order_id")),
                pm.aggregate(n=pm.count()),
                pm.having(pm.col("n") > 1),
            )
        ),
        "non_null_order_id": pm.ref("orders").pipe(
            pm.query(
                pm.where(pm.col("order_id").is_null()), pm.select(pm.col("order_id"))
            )
        ),
    },
    data_root="data",
    timeout=30,
)
if report.ok:
    report.save("orders.malloy", warnings_as_errors=True)
else:
    print(report.diagnostics, report.checks, report.error)
```

1. Compose immutable source expressions and reusable clauses. Name declarations
   with `.define(**sources)` or `.queries(**queries)`. For an existing field, use
   `draft.define(orders=draft["orders"].replace(revenue=pm.col("amount").sum()))`.
   Pass `pm.col("amount").sum().doc("revised description")` to replace the binding's directly
   attached `#(doc)` text. Shared statement tags and block annotations stay intact.
   Review `.diff()` and update affected assertions.
2. Call `.check(**connection_options)` for compiler diagnostics, metadata, and
   advisory documentation warnings. Fix errors using their authored locations.
3. Call `.validate(checks, **connection_options)` for named business assertions.
   Each check is a source/query fragment returning counterexamples. Zero rows passes. A failed check retains one
   example in `check.result.rows()`. Query errors also fail validation.
4. Inspect diagnostics and checks, then revise the candidate. Compiler success
   alone does not establish correct grain, cardinality, or metric meaning.
5. Save the accepted revision with `report.save(path)`. Failed validation blocks
   saving. `warnings_as_errors=True` also blocks documentation warnings.
   `Draft.save()` saves unfinished work. Loaded files reject observed external
   changes, and validated saves also check imported files.
6. Reload after saving and revalidate when data, imports, or the destination changes.
   Reports describe the captured revision and data at check time.

`query.preview(limit=20, timeout=...)` limits returned rows and rejects COPY.
Aggregation may still scan the input. Validation shares one timeout budget across
compilation and assertions, and closes owned resources. Borrowed connections
remain caller-owned.

## Use explicit expressions

Use `pm.col("amount")`, `pm.col("labels", "region")`, and `pm.given("minimum")`
for references. Use `pm.lit("North")` for a standalone literal. Python values beside
an expression also become literals: `pm.col("region") == "North"`.

Combine predicates with `&`, `|`, and `~`, parenthesizing each comparison.
Use `.str.lower()` to normalize text and `.dt.year()` or `.dt.truncate("month")`
for time expressions. Scalar clause arguments require expressions. Use
`pm.raw_expr(text)` for additional scalar Malloy grammar and `pm.syntax(text)` for
additional model or query grammar. Neither boundary is needed for ordinary field
references, arithmetic, predicates, or aggregates.

## Import and roundtrip deliberately

`pm.read_model` preserves source text while exposing named expressions for scoped
edits. `draft.to_python()` emits editable scalar constructors and model syntax.
Supported scalar expressions are rendered canonically, preserving semantics while
allowing their spelling to change. Comments and surrounding syntax stay verbatim.
Read and save an unchanged draft for exact file preservation. After editing the
generated Python, rerun the relevant queries and assertions.

Read [API patterns](references/api.md) for composition, scoped editing, import
snapshots, and Python emission. Read [modeling practices](references/modeling.md)
for key proofs, join checks, metric definitions, and deterministic ranking.

Keep business decisions in documentation and accompanying evidence. Reuse choices
the user already settled. Clarify unresolved definitions when the alternatives
materially change the answer. Do not invent thresholds or require approval for
every edit. Documentation checks are mechanical evidence, not business review.
