# Python authoring patterns

## Compose reusable expressions

```python
import pymalloy as pm

regional = (
    pm.view()
    .group_by(pm.col("region"))
    .aggregate(pm.col("revenue"))
    .order_by(pm.col("revenue").desc(), pm.col("region"))
)
orders = (
    pm.table("orders.parquet")
    .dimension(order_date=pm.col("created_at").cast("date"))
    .measure(revenue=pm.col("amount").sum().doc("Gross amount in USD."))
    .view(by_region=regional.doc("Revenue by region with deterministic ranking."))
    .doc("One row per order.")
)
candidate = (
    pm.draft()
    .sources(orders=orders)
    .queries(regional_report=pm.source("orders").pipe(regional))
)
print(candidate.text)
```

`table`, `sql`, and `source` create anonymous expressions. Names enter through keyword
bindings. Use `col` for field paths, `given` for parameters, and `lit` for values.
Operators build scalar expressions, and values beside expressions become literals.
Every edit returns a new value. Clauses can be reused across sources and queries.

`source.join_one(name, source, on=...)`, `join_many`, and `join_cross` declare
relationships. Use `pm.Expr.raw(text)` for additional scalar expressions,
`pm.Source.raw(text)` for relation syntax, `pm.View.raw(text)` for query stages, and `draft.append(text)`
for complete declarations. These preserve text verbatim.
Use `read_model` when raw text needs named editing slots.

## Read and edit existing models

```python
from pathlib import Path

original = pm.read_model(Path("orders.malloy"))
candidate = original.sources(
    orders=original["orders"].replace(
        revenue=(pm.col("amount").sum() - pm.col("refunds").sum()).doc(
            "Net amount in USD."
        )
    ),
    north_orders=pm.source("orders")
    .where(pm.col("region") == "North")
    .doc("Orders in the North region."),
)
print(candidate.diff())
```

Review whether refunds belong in revenue before adopting that definition, and
update its description and assertions. `.replace` edits named right-hand sides
within the selected scope. Supplying `.doc` replaces the owned documentation
route. Omitting `.doc` retains the description. `.annotate(text, route=...)`
replaces another owned route. Shared statement tags stay intact. A nested view or join
owns its own field names. Missing and ambiguous names fail explicitly.

`pm.read_model(model.source())` branches a closed snapshot whose imports remain
captured even if files change. `.include("relative.malloy")` adds a live import
relative to `draft.url`. Imports must precede their consumers.

For givens, compose the installed Malloy syntax explicitly:

```python
candidate = pm.draft(
    "##! experimental.givens\ngiven: minimum :: number is 0\n"
).sources(orders=orders.where(pm.col("amount") > pm.given("minimum")))
```

## Roundtrip source through Python

```python
code = original.to_python(name="restored")
namespace = {}
exec(code, namespace)
restored = namespace["restored"]
assert restored["orders"]["revenue"].equals(original["orders"]["revenue"])
```

The emitted Python uses source and query constructors for parser-recognized
structure, with `pm.col`, literals, operators and aggregate methods for scalar
expressions. Unrepresented grammar remains in syntax fragments. Edit the
constructors directly. Supported scalar
expressions may change spelling while preserving meaning. Named bindings, captured
imports, comments, and surrounding syntax remain available. Reading a file and
saving it unchanged preserves its exact source text.

## Check and execute

```python
report = pm.connect(data_root="data").check(candidate)
print(report.ok, report.diagnostics, report.model.sources)
model = pm.connect(data_root="data").model(candidate)
try:
    print(
        model.query(malloy="run: orders -> { select: * }").preview(limit=10).to_pylist()
    )
finally:
    model.close()
```

`pm.connect(...)` owns native runtime settings. Call `connection.check(candidate)`,
`connection.model(candidate)`, or `connection.validate(candidate, checks)`. Pass
an existing DuckDB connection to `pm.connect(native)` to preserve caller ownership
and settings. Reuse a model for repeated previews.

Pass `documentation=DocumentationPolicy()` from `pymalloy.validation` to enable
documentation checks. Their warnings are advisory. `Validation.save(warnings_as_errors=True)`
can make them blocking. Compilation errors and failed, errored, or skipped data
checks make `Validation.ok` false.

## Discover installed instructions

```python
import pymalloy.agent as agent

print(agent.agent_plugin().tree())
print(agent.agent_skill().body)
```

Wheel, source, and editable installs carry the skill tree as package assets.
The base package includes `agent-plugins` to read it. Marimo discovers `pymalloy.agent` through its capability entry
point. `help(pymalloy.agent)` introduces the installed API.

Pass a composed source/query directly to a retained model:

```python
expression = pm.source("orders").pipe(pm.view().aggregate(pm.col("revenue")))
result = model.query(expression).run()
```

This uses the same compiler path as `model.query(malloy="run: ...")`. A string
selection names a saved query, while `malloy=` accepts complete native query text.
