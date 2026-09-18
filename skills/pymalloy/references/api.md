# Python authoring patterns

## Compose reusable expressions

```python
import pymalloy as pm

regional = pm.query(
    pm.group_by(pm.col("region")),
    pm.aggregate(pm.col("revenue")),
    pm.order_by(pm.col("revenue").desc(), pm.col("region")),
)
orders = (
    pm.table("orders.parquet")
    .extend(
        pm.dimension(order_date=pm.col("created_at").cast("date")),
        pm.measure(revenue=pm.col("amount").sum().doc("Gross amount in USD.")),
        pm.view(
            by_region=regional.doc("Revenue by region with deterministic ranking.")
        ),
    )
    .doc("One row per order.")
)
candidate = (
    pm.draft()
    .define(orders=orders)
    .queries(regional_report=pm.ref("orders").pipe(regional))
)
print(candidate.text)
```

`table`, `sql`, and `ref` create anonymous expressions. Names enter through keyword
bindings. Use `col` for field paths, `given` for parameters, and `lit` for values.
Operators build scalar expressions, and values beside expressions become literals.
Every edit returns a new value. Clauses can be reused across sources and queries.

`pm.join(name, source, on=..., kind="one" | "many" | "cross")` requires an explicit
relationship. Use `pm.raw_expr(text)` for additional scalar expressions,
`pm.syntax(text)` for additional source or query clauses, and `draft.append(text)`
for complete declarations. These preserve text verbatim.
Use `read_model` when raw text needs named editing slots.

## Read and edit existing models

```python
from pathlib import Path

original = pm.read_model(Path("orders.malloy"))
candidate = original.define(
    orders=original["orders"].replace(
        revenue=(pm.col("amount").sum() - pm.col("refunds").sum()).doc(
            "Net amount in USD."
        )
    ),
    north_orders=pm.ref("orders")
    .extend(pm.where(pm.col("region") == "North"))
    .doc("Orders in the North region."),
)
print(candidate.diff())
```

Review whether refunds belong in revenue before adopting that definition, and
update its description and assertions. `.replace` edits named right-hand sides
within the selected scope. Supplying `.doc` also replaces directly attached
single-line `#"` text. Omitting `.doc` retains the description. Shared statement
tags and block annotations stay intact. A nested view or join
owns its own field names. Missing and ambiguous names fail explicitly.

`pm.read_model(model.source())` branches a closed snapshot whose imports remain
captured even if files change. `.include("relative.malloy")` adds a live import
relative to `draft.url`. Imports must precede their consumers.

For givens, compose the installed Malloy syntax explicitly:

```python
candidate = pm.draft("##! experimental.givens\ngiven: minimum :: number is 0\n").define(
    orders=orders.extend(pm.where(pm.col("amount") > pm.given("minimum")))
)
```

## Roundtrip source through Python

```python
code = original.to_python(name="restored")
namespace = {}
exec(code, namespace)
restored = namespace["restored"]
assert restored["orders"]["revenue"].equals(original["orders"]["revenue"])
```

The emitted Python uses `pm.col`, literals, operators, and aggregate methods
inside `pm.draft` and `pm.syntax`. Edit those operations directly. Supported scalar
expressions may change spelling while preserving meaning. Named bindings, captured
imports, comments, and surrounding syntax remain available. Reading a file and
saving it unchanged preserves its exact source text.

## Check and execute

```python
report = candidate.check(data_root="data")
print(report.ok, report.diagnostics, report.model.sources)
model = candidate.compile(data_root="data")
try:
    print(model.query(malloy="run: orders -> { select: * }").preview(limit=10).rows())
finally:
    model.close()
```

`.check`, `.compile`, and `.validate` accept the data connection options of
`pm.model`. Reuse a compiled model for repeated previews. `connection=` borrows
DuckDB and preserves caller ownership and settings. `.validate()` compiles once
for all named assertions.

Documentation warnings are advisory. `Validation.save(warnings_as_errors=True)`
can make them blocking. Compilation errors and failed, errored, or skipped data
checks make `Validation.ok` false.

## Discover installed instructions

```python
import pymalloy.agent as agent

print(agent.agent_plugin().tree())
print(agent.agent_skill().body)
```

Wheel, source, and editable installs carry the selected skill tree through
`agent-plugins`. Marimo discovers `pymalloy.agent` through its capability entry
point. `help(pymalloy.agent)` introduces the installed API.
