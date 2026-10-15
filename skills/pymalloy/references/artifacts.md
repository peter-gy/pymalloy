# Author, validate, export, replay

[Malloy](https://docs.malloydata.dev/) defines the semantic model.
[DuckDB](https://duckdb.org/docs/stable/) executes its compiled SQL.

Establish the deliverables before writing queries. A reusable dataset needs its
semantic model and imports, selected query, bound parameters, input identities,
and output schema. Keep user situations and research annotations in the consuming
project. PyMalloy's source bundle owns Malloy files and explicit data bindings.

Use `pm.source("orders").measure(...)` when deriving a source from an existing named
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
        .sources(
            orders=pm.table(data)
            .primary_key("id")
            .measure(
                revenue=pm.col("amount")
                .sum()
                .doc("Booked value in source price units.")
            )
            .doc("One order per id in this captured input.")
        )
        .sources(
            selected=pm.source("orders")
            .where(pm.col("amount") >= pm.given("minimum"))
            .doc("Orders meeting the selected minimum amount.")
        )
        .queries(
            by_region=pm.source("selected").pipe(
                pm.view()
                .group_by(pm.col("region"))
                .aggregate(pm.col("revenue"))
                .order_by(pm.col("region"))
            )
        )
    )
    parameters = {"minimum": 10}
    checks = {
        "nonempty": pm.source("orders").pipe(
            pm.view().aggregate(rows=pm.count()).having(pm.col("rows") == 0)
        ),
        "unique_id": pm.source("orders").pipe(
            pm.view()
            .group_by(pm.col("id"))
            .aggregate(rows=pm.count())
            .having(pm.col("rows") > 1)
        ),
        "non_null_id": pm.source("orders").pipe(
            pm.view().where(pm.col("id").is_null()).select(pm.col("id"))
        ),
    }
    with pm.connect() as con:
        accepted = con.validate(candidate, checks, givens=parameters).require_valid()
    artifact = bundle(
        accepted,
        workspace / "export",
        files={data: data},
        query="by_region",
        givens=parameters,
    )
    manifest = json.loads(artifact.manifest.read_text())
    data.unlink()
    relocated = workspace / "relocated"
    artifact.model.parent.rename(relocated)
    connection = pm.connect(data_root=relocated / manifest["data_root"])
    model = connection.model(relocated / manifest["model"])
    try:
        rows = model.query(manifest["query"]).run(givens=manifest["givens"]).to_pylist()
        assert rows == [
            {"region": "North", "revenue": 12},
            {"region": "South", "revenue": 20},
        ]
    finally:
        connection.close()
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
parameters. The generated `replay.py` executes with the installed runtime. The consuming
project owns hash verification, version enforcement, output comparison, and
rerunning assertions.
Retain environment specifications and expected results in the producing project.
Compare SQL structure as well as typed results when checking Python
reconstruction. Matching rows on one snapshot is insufficient evidence of general
semantic equivalence. Nested ordering, nulls, large integers and denominators are
part of the comparison.

## Prepared Python data

Use `pm.data(prepared, name="orders")` for captured Python inputs and retain the
returned source through grammar composition. Capture after deliberate `.collect()`
for lazy data. Validate the candidate, then call `bundle(accepted, directory)`.
Both a validation and its `.source` retain managed input owners. Passing the
validation also records its checks and accepted parameters. Export uses captured
values. Retain the producer to rebuild them.

Keep preparation, model construction, validation, and export in separate marimo
cells with direct variable references. Retain the notebook or Python producer
script alongside the bundle. It owns the preparation logic and external rebuild
requirements. Replay uses bundled Parquet. Rebuilding requires deliberately
rerunning the producer, validating, and exporting a new revision.
