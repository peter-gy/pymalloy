# Author, validate, export, replay

Establish the deliverables before writing queries. A reusable dataset needs its
semantic model and imports, selected query, bound parameters, input identities,
and output schema. Keep user situations and research annotations in the consuming
project. PyMalloy's source bundle owns Malloy files and explicit data bindings.

Use `pm.ref("orders").extend(...)` when deriving a source from an existing named
source. Use `draft["orders"].replace(...)` when editing that source's definition.
The latter returns its expression, so assigning it under another name copies the
expression. Prefer native Malloy text for syntax that reads more clearly that way.

This example requires `pymalloy[headless]` and writes into a temporary workspace:

```python
import json
import tempfile
from pathlib import Path

import pymalloy as pm
from pymalloy.export import bundle

with tempfile.TemporaryDirectory() as temporary:
    workspace = Path(temporary)
    data = workspace / "orders.csv"
    data.write_text("id,region,amount\n1,North,12\n2,South,20\n3,North,8\n")
    candidate = (
        pm.draft("##! experimental.givens\ngiven: minimum :: number is 0\n")
        .define(orders=pm.table(data).extend(
            pm.primary_key("id"),
            pm.measure(revenue=pm.col("amount").sum().doc("Booked value in source price units.")),
        ).doc("One order per id in this captured input."))
        .define(selected=pm.ref("orders").extend(
            pm.where(pm.col("amount") >= pm.given("minimum")),
        ).doc("Orders meeting the selected minimum amount."))
        .queries(by_region=pm.ref("selected").pipe(pm.query(
            pm.group_by(pm.col("region")),
            pm.aggregate(pm.col("revenue")),
            pm.order_by(pm.col("region")),
        )))
    )
    parameters = {"minimum": 10}
    checks = {
        "nonempty": pm.ref("orders").pipe(pm.query(
            pm.aggregate(rows=pm.count()), pm.having(pm.col("rows") == 0),
        )),
        "unique_id": pm.ref("orders").pipe(pm.query(
            pm.group_by(pm.col("id")), pm.aggregate(rows=pm.count()),
            pm.having(pm.col("rows") > 1),
        )),
        "non_null_id": pm.ref("orders").pipe(pm.query(
            pm.where(pm.col("id").is_null()), pm.select(pm.col("id")),
        )),
    }
    accepted = candidate.validate(checks, givens=parameters).require_valid()
    artifact = bundle(
        accepted, workspace / "export", files={data: data},
        query="by_region", givens=parameters,
    )
    manifest = json.loads(artifact.manifest.read_text())
    data.unlink()
    relocated = workspace / "relocated"
    artifact.model.parent.rename(relocated)
    model = pm.model(relocated / manifest["model"], data_root=relocated / manifest["data_root"])
    try:
        rows = model.query(manifest["query"]).run(givens=manifest["givens"]).rows()
        assert rows == [{"region": "North", "revenue": 12}, {"region": "South", "revenue": 20}]
    finally:
        model.close()
```

The bundle contains formatted `model.malloy`, imported Malloy files, copied data,
and `bundle.json` with the selected query, exact parameter bindings, compiler
version and SHA-256 identities. Preserve this directory structure when moving it.
`Validation.source` is the closed graph accepted by validation. `Model.source()`
provides a closed graph from a retained compiled model.

Bind table inputs explicitly. A `Path` key matches a table authored with
`pm.table(Path(...))`. A string key matches that exact Malloy table path. Relative
string aliases also expose files to SQL readers through DuckDB's search path.
PyMalloy rewrites compiler-selected table references and import literals, and
leaves SQL text intact. Registered tables, database state, remote readers and
computed reader paths require their own replay setup. Review those dependencies
before calling an artifact self-contained.

Explicit files are copied at export time. Keep them stable between validation
and export, or revalidate the copied data. Managed `pm.data` inputs retain their
captured values and are checked for Parquet integrity during export.

After export, execute the emitted Malloy from the new directory with the recorded
parameters. The generated `replay.py` executes with the installed runtime. It does
not verify manifest hashes, enforce versions, compare output, or rerun assertions.
Retain environment specifications and expected results in the producing project.
Compare SQL structure as well as typed results when checking Python
reconstruction. Matching rows on one snapshot is insufficient evidence of general
semantic equivalence. Nested ordering, nulls, large integers and denominators are
part of the comparison.

## Prepared Python data

Use `pm.data(prepared, name="orders")` for captured Python inputs and retain the
returned source through grammar composition. Capture after deliberate `.collect()`
for lazy data. Validate the candidate, then call `bundle(accepted, directory)`.
Do not extract `.source` first: the validation owns managed input resources and
parameters. Export never reruns preparation.

Keep preparation, model construction, validation, and export in separate marimo
cells with direct variable references. Retain the notebook or Python producer
script alongside the bundle. It owns the preparation logic and external rebuild
requirements. Replay uses bundled Parquet. Rebuilding requires deliberately
rerunning the producer, validating, and exporting a new revision.
