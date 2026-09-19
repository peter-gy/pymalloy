# Bundle models and inputs

A source bundle packages Malloy files, captured imports, and declared data files
with a selected query and its givens. Use it to move an analysis between directories
or hand its model and inputs to another person. Preparing and replaying a bundle
requires `pymalloy[headless]`.

## Validate and export

This example uses literal SQL data so it can run without input files:

```python
import pymalloy as pm
from pymalloy.export import bundle

candidate = (
    pm.draft()
    .define(orders=pm.sql(
        "SELECT * FROM (VALUES ('North', 20), ('South', 30), ('North', 22)) t(region, amount)"
    ).extend(
        pm.measure(revenue=pm.col("amount").sum().doc("Booked amount in USD.")),
    ).doc("One row per order."))
    .queries(by_region=pm.ref("orders").pipe(pm.query(
        pm.group_by(pm.col("region")),
        pm.aggregate(pm.col("revenue")),
        pm.order_by(pm.col("region")),
    )))
)
checks = {
    "known_revenue": pm.ref("orders").pipe(pm.query(
        pm.aggregate(pm.col("revenue")),
        pm.having(pm.col("revenue") != 72),
    )),
}
accepted = candidate.validate(checks).require_valid()
artifact = bundle(accepted, "regional-sales", query="by_region")
```

The destination must be new and its parent must exist. Validation executes the
supplied counterexample queries. Bundling packages that accepted source revision,
checks import closure, and records the selected query. It does not execute the
selected query or rerun the assertions.

```text
regional-sales/
  model.malloy   Root model with rewritten file and import references
  sources/      Captured imports, when present
  data/         Explicitly bound files and captured dataframe inputs
  model.py      Editable Python reconstruction of the bundled Malloy
  bundle.json   Query, givens, compiler version, file hashes, input/check records
  replay.py     Load the bundled model and execute the selected query
```

## Include data

For [captured Python data](dataframes.md), pass the `Validation` directly to
`bundle`. It retains the `pm.data(...)` input owners. Extracting `.source` first
keeps the source text but drops those owners from the export argument.

For a model that references an ordinary file, bind that file explicitly:

```python
# accepted is a validation of a model using duckdb.table('orders.parquet').
artifact = bundle(
    accepted, "orders-export", query="by_region",
    files={"orders.parquet": "data/orders.parquet"},
)
```

Ordinary files are copied at export time. Validation does not freeze them. Managed
`pm.data` inputs retain their captured values, and export verifies their Parquet
hashes. String binding keys match exact Malloy table paths. For a table authored
with `pm.table(Path(...))`, use a `Path` key. The
[export reference](../reference/export.md#source-bundles) defines these bindings.

SQL reader text remains unchanged. Declare its local files and review absolute
paths, catalog tables, remote URLs, and computed paths before claiming a bundle is
self-contained. Copies cover declared inputs, not arbitrary dependencies of SQL.

## Replay after moving

Move the whole bundle, then run its script with the required Python environment:

```sh
python regional-sales/replay.py
```

The script uses the recorded connection name, executes the query and closes its
model. It rejects a copied input alias that resolves to a different file in the
current directory. Undeclared SQL readers remain the caller's responsibility. To inspect the materialized
result in Python:

```python
import runpy

result = runpy.run_path("regional-sales/replay.py")["result"]
print(result.rows())
# [{'region': 'North', 'revenue': Decimal('42')},
#  {'region': 'South', 'revenue': Decimal('30')}]
```

Replay uses the installed compiler and DuckDB. The manifest records the compiler
version and file hashes, but the script does not enforce that version, verify
hashes, compare an expected output, or rerun the recorded assertions. Retain your
environment specification and compare replayed values when reproducibility is a
requirement. Declare deterministic ordering, including tie-breakers and nested
queries, when row order is significant.

`model.py` reconstructs Malloy grammar against bundled files. The producing
notebook or script retains Python preparation logic. Rebuilding inputs means
running that producer, validating a new revision, and exporting to a new directory.

## Use bundles in dataset production

Keep the following evidence beside a dataset produced from a bundle:

- The user situation and analytical question, distinguishing supplied intent from
  proposed interpretations.
- The selected query and givens, output data, and comparison policy used for replay.
- Field definitions, units, grain at each nested level, denominators, coverage,
  and null meaning. Native Malloy descriptions can carry reusable definitions.
- Assertion outcomes, human review status, environment versions, and input provenance.

The bundle provides the model, declared inputs, bindings, and part of this evidence.
The consuming project owns the task record, output schema annotations, expected
results, and any visualization constraints. Documentation lint checks descriptions
are present. It does not derive or validate those research-specific records.

To distribute a runnable notebook, use [notebook export](export.md). It prepares
ordered cells and an execution profile, a separate operation from copying a source
bundle.
