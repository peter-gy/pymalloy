# Bundle models and inputs

`pymalloy.export.bundle` writes a [Malloy](https://docs.malloydata.dev/) source
graph, copied inputs, a manifest, and a replay script into a new directory.
Prepare the model, validate it, and replay the bundled query:

```python
import runpy
from pathlib import Path
from tempfile import TemporaryDirectory

import pymalloy as pm
from pymalloy.export import bundle

candidate = pm.draft().queries(
    total=pm.sql("SELECT * FROM (VALUES (20), (22)) t(amount)").pipe(
        pm.view().aggregate(revenue=pm.col("amount").sum())
    )
)
with pm.connect() as con:
    accepted = con.validate(candidate).require_valid()
with TemporaryDirectory() as directory:
    artifact = bundle(accepted, Path(directory) / "sales", query="total")
    result = runpy.run_path(str(artifact.model.parent / "replay.py"))["result"]
    print(result.to_pylist())
```

Expected output is `[{'revenue': Decimal('42')}]`.
The destination must be new and its parent must exist. Bundling parses the source,
checks import closure, copies declared inputs, and records the selection.
Validation executes the supplied checks. Replay executes the selected query.

```text
sales/
  model.malloy   Root source with rewritten imports and file references
  sources/       Captured imports, when present
  data/          Bound files and captured Python inputs
  model.py       Editable Python reconstruction against bundled files
  bundle.json    Selection, givens, compiler version, hashes, validation outcomes
  replay.py      Load the bundle and execute its selected query
```

## Copy a local input and replay after moving

```python
import runpy
from pathlib import Path
from tempfile import TemporaryDirectory

import pymalloy as pm
from pymalloy.export import bundle

with TemporaryDirectory() as directory:
    workspace = Path(directory)
    data = workspace / "orders.csv"
    data.write_text("amount\n20\n22\n")
    candidate = pm.draft().queries(
        total=pm.table(data).pipe(pm.view().aggregate(revenue=pm.col("amount").sum()))
    )
    with pm.connect() as con:
        accepted = con.validate(candidate).require_valid()
    artifact = bundle(accepted, workspace / "sales", files={data: data}, query="total")
    data.unlink()
    moved = workspace / "relocated"
    artifact.model.parent.rename(moved)
    result = runpy.run_path(str(moved / "replay.py"))["result"]
    print(result.to_pylist())
```

The relocated bundle still returns revenue `42` after the original file is deleted.
A `Path` binding key matches a table authored with `pm.table(Path(...))`.
A string key matches the exact Malloy table path. Relative string aliases also
expose files to SQL readers through [DuckDB](https://duckdb.org/docs/stable/),
the replay engine's file search path. SQL reader text remains unchanged.

Explicit files are copied at export time. Keep them stable between validation
and export, or revalidate the copied data. [Captured Python inputs](dataframes.md)
retain their construction-time values and export verifies their Parquet hashes.
Both `Validation` and `ModelSource.inputs` retain captured owners. Passing
`Validation` also supplies accepted givens, connection name, and check outcomes.

Review absolute SQL paths, catalog tables, remote URLs, and computed reader paths
before calling a bundle self-contained. Bind or separately supply every dependency
needed for replay.

## Interpret replay evidence

Run `python PATH_TO_BUNDLE/replay.py` in the required Python environment.
It uses the recorded connection name and givens and closes its connection.
It rejects copied input aliases shadowed by a different current-directory file.

The manifest records hashes and compiler version. The script uses the installed
runtime. Version enforcement, hash verification, output comparison, and rerunning
assertions belong to the consuming project. Retain an environment specification
and expected results when reproducibility is required. Declare deterministic
ordering, including tie-breakers and nested query order, when order matters.

`model.py` reconstructs the model's grammar. Keep the producer notebook or script
to rebuild prepared data. Record the analytical question, field definitions,
units, grain, denominators, coverage, null meaning, and human review beside the
produced dataset. A bundle captures files and bindings, while that project owns
the intent and comparison policy.

See the [export reference](../reference/export.md#source-bundles) for the manifest
and binding contracts. Use [notebook export](export.md) to distribute an executable
notebook with an execution profile.
