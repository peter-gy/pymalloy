# Publish Python data as a Malloy model

Use `pm.data(frame)` to capture prepared Python data in a semantic model. The
input travels with the draft, validation result, and exported bundle.
Install `pymalloy[server,dataframes]` for this example:

```python
import polars as pl
import pymalloy as pm
from pymalloy.export import bundle

orders = pl.DataFrame({
    "id": [1, 2, 3],
    "region": ["North", "South", "North"],
    "amount": [12, 20, 8],
})
prepared = orders.filter(pl.col("amount") >= 10)
candidate = (
    pm.draft()
    .define(orders=pm.data(prepared, name="orders").extend(
        pm.primary_key("id"),
        pm.measure(revenue=pm.col("amount").sum().doc("Booked amount in USD.")),
    ).doc("One retained order per id, with amount of at least 10 USD."))
    .queries(by_region=pm.ref("orders").pipe(pm.query(
        pm.group_by(pm.col("region")),
        pm.aggregate(pm.col("revenue")),
        pm.order_by(pm.col("region")),
    )))
)
checks = {
    "unique_id": pm.ref("orders").pipe(pm.query(
        pm.group_by(pm.col("id")),
        pm.aggregate(n=pm.count()),
        pm.having(pm.col("n") > 1),
    )),
}
accepted = candidate.validate(checks).require_valid()
artifact = bundle(accepted, "booked-sales", query="by_region")
```

`booked-sales/model.malloy` reads ordinary Parquet files under `data/`. The bundle
also includes imported models, editable Python grammar in `model.py`,
`bundle.json`, and `replay.py`. Run
`python booked-sales/replay.py` to execute the selected query against the frozen
inputs. The script exposes a `result` when loaded with `runpy.run_path`.

## Capture once, reuse the same values

`pm.data` copies data through Arrow IPC at construction. Changing the original
frame or a mutable backing buffer cannot change the captured input. The first
compilation or widget use writes Parquet once. Schema discovery, query execution,
validation, and export use those bytes. Closing a model does not invalidate a
retained draft or validation result.

Polars DataFrames, Arrow Tables and RecordBatches, pandas DataFrames, and
materialized producers implementing Arrow's `__arrow_c_stream__` interface are
accepted. PyArrow is required. pandas is optional and its index is excluded.
Call `.collect()` on lazy data explicitly before passing it to `pm.data`.

Supported data includes nested lists and records, nulls, booleans, strings,
integers, floats, decimals up to precision 38, dates, and timestamps. Nanosecond
timestamps are normalized to microseconds only when exact. Unsupported types,
submicrosecond values, or a Parquet roundtrip that changes values or schema raise
an error. Cast deliberately in the preparation code when another representation
is appropriate. Query ordering still requires `pm.order_by`.

Reuse a captured source expression to share one input. Two separate `pm.data`
calls represent separate capture origins. Give distinct inputs distinct names.
`draft.inputs` exposes names, row counts, fingerprints, and detached Arrow values.
`draft.text` uses logical input paths. Use `bundle(accepted, ...)` to publish files.
Plain `.save()` rejects drafts with managed inputs.

`draft.to_python(inputs={"orders": "prepared"})` reconstructs the symbolic model
with an explicit Python variable binding. It preserves shared input references.
It cannot infer the code that produced `prepared`.

## Keep preparation in the notebook

In marimo, put dataframe preparation, model construction, validation, and export
in separate cells. Refer to their Python variables directly so marimo tracks the
dependencies. Keep the notebook alongside the bundle as the editable record of
how its inputs were prepared. For ordinary Python, retain the producer script.

The bundle publishes the accepted data snapshot. Its `model.py` reconstructs the
Malloy grammar against bundled files. The notebook retains the original dataframe
operations and the model's construction logic.

Replay runs `replay.py` against frozen Parquet. Rebuilding means explicitly rerunning
the notebook or producer script, validating the new result, and exporting to a new
directory. External files, services, environment settings, and randomness remain
requirements of that Python program. Existing bundles are never overwritten.
