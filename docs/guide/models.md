# Reuse models and select queries

Compile a model once and run its queries against current data:

```python
from pathlib import Path
import pymalloy as pm

model = pm.model(Path("examples/orders.malloy"), data_root="examples")
for query in model.queries:
    print(query.name, query.kind, query.location)
result = model.query("orders.by_region").run()
print(result.rows())
```

`model.queries` contains typed `QueryDescriptor` records. Kinds are `run`, `named`,
`view`, and `sql`. Names identify queries within the model. `run:0` and `sql:0`
identify the first run and SQL cell respectively. All source coordinates and
ordinal query names are zero-based. Inserting a cell can change ordinal names.

`model.query()` selects the final run, or the single available query. Otherwise,
choose a name. An ad hoc query uses
`model.query(malloy="run: orders -> by_region")` in Python and
`model.query({ malloy: "run: orders -> by_region" })` in TypeScript.

A model snapshots imports and schemas. Its queries read current data. Compile a
new model after a schema or source change. Python models clean up when their last
reference is released. `model.close()` releases the compiler and owned connection
early. Other models remain usable.

`model.source()` returns a `ModelSource` with the root URL, text, and captured
imports. `pm.model(snapshot)` hydrates it in Python. TypeScript uses
`session.model({ source: snapshot })`. Pass data options when hydrating a snapshot.
