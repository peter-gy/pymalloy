# Edit an existing model

`pm.read_model` parses a [Malloy](https://docs.malloydata.dev/) file into a draft
with named editing slots. Validate the edited model before saving it:

```python
from pathlib import Path
from tempfile import TemporaryDirectory

import pymalloy as pm

text = """source: orders is duckdb.sql('SELECT 20 AS amount, 2 AS refund') extend {
  #" Gross booked amount in USD.
  measure: revenue is amount.sum()
}
query: total is orders -> { aggregate: revenue }
"""
with TemporaryDirectory() as directory:
    path = Path(directory) / "orders.malloy"
    path.write_text(text, encoding="utf-8", newline="\n")
    original = pm.read_model(path)
    candidate = original.sources(
        orders=original["orders"].replace(
            revenue=(pm.col("amount").sum() - pm.col("refund").sum()).doc(
                "Booked amount less refunds, in USD."
            )
        )
    )
    print(candidate.diff())
    with pm.connect() as con:
        accepted = con.validate(candidate).require_valid()
        print(con.model(candidate).query("total").run().to_pylist())
    accepted.save()
    assert original.text == text
```

The diff changes `revenue` and its owned description. The query returns
`[{'revenue': Decimal('18')}]`. The original draft remains unchanged.

## Select the scope you intend to edit

`draft["orders"]` returns the source expression. Index it again to select a
field, saved view, or explicit join. A nested view owns its field names.
`.replace(**definitions)` edits within the selected scope. Missing names raise
`KeyError`. Ambiguous names raise `ValueError`.

A replacement carrying `.doc(...)` updates that owned description route.
An omitted route retains its existing annotation. Shared statement annotations
and surrounding comments remain intact. `.annotate(text, route=...)` edits
another owned route.

Use `pm.source("orders").where(...)` to derive a separate source from a named
source. Assigning `draft["orders"]` under another name copies its expression.
`pm.read_model(model.source())` branches captured imports and input owners from
a compiled model. `.include("base.malloy")` adds a live import to an open draft
before its consumers.

## Reconstruct editable Python

```python
import pymalloy as pm

original = pm.read_model(
    "source: orders is duckdb.sql('SELECT 20 AS amount') extend {measure: revenue is amount.sum()}"
)
code = original.to_python(name="candidate")
namespace = {}
exec(code, namespace)
candidate = namespace["candidate"]
assert candidate["orders"]["revenue"].equals(original["orders"]["revenue"])
print(candidate.names)
```

Expected output is `('orders',)`. The emitted code uses constructors for supported
structure and `Source.raw`, `View.raw`, or `Expr.raw` for other grammar.
It preserves source identity and captured imports. Supported scalars render
canonically, so rerun the affected queries after editing generated Python.

## Save with conflict detection

Reading and saving an unchanged file preserves exact UTF-8 bytes, including line
endings. A save to the loaded path checks its observed contents. If another writer
changed or deleted it, reload and reconcile before saving. `overwrite=True`
permits replacing an unrelated destination. It keeps the loaded-file conflict
check. Reload after a successful save to establish the next observed revision.

Parents must exist. Writes publish complete text atomically. The revision check
cannot lock concurrent writers. Validated imports must remain unchanged and be
saved beside their original root. Use a [source bundle](bundles.md) to relocate
a captured graph and its inputs.
