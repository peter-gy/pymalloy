# Capture Python data

`pm.data(frame)` captures materialized Python values so they travel with a model.
Install `pymalloy` and [Polars](https://docs.pola.rs/), a dataframe
library, for this example:

```python
import polars as pl
import pymalloy as pm

orders = pl.DataFrame({"region": ["North", "South", "North"], "amount": [12, 20, 8]})
prepared = orders.filter(pl.col("amount") >= 10)
captured = pm.data(prepared, name="orders")
candidate = pm.draft().queries(
    by_region=captured.pipe(
        pm.view().group_by("region").aggregate(revenue=pm.col("amount").sum()).order_by("region")
    )
)
with pm.connect() as con:
    with con.model(candidate) as model:
        snapshot = model.source()
        print(model.query().run().to_pylist())
    print(con.model(snapshot).query().run().to_pylist())
assert snapshot.inputs[0].rows == 2
```

Both executions return:

```text
[{'region': 'North', 'revenue': Decimal('12')}, {'region': 'South', 'revenue': Decimal('20')}]
```

[Malloy](https://docs.malloydata.dev/) defines the grouping and aggregate.
[DuckDB](https://duckdb.org/docs/stable/), an embedded SQL engine, reads the
captured values. The snapshot retains its input after the first model closes.

## Capture once and reuse

Construction copies values through [Arrow](https://arrow.apache.org/docs/), a
columnar data format. Mutation of the producer or its backing buffers leaves
the capture unchanged. The first compilation or widget request writes verified
[Parquet](https://parquet.apache.org/docs/), a columnar file format, once.
Schemas, execution, validation, and bundles use those bytes.

Accepted producers include Polars DataFrames, Arrow Tables and RecordBatches,
[pandas](https://pandas.pydata.org/docs/) DataFrames, and materialized objects
implementing Arrow's `__arrow_c_stream__` interface. PyMalloy installs
[PyArrow](https://arrow.apache.org/docs/python/), the Python Arrow library, on
native Python. Install producer libraries such as Polars or pandas separately.
A pandas index is excluded. Collect lazy frames explicitly before capture.

Supported values include nested lists and records, nulls, booleans, strings,
integers, floats, decimals up to precision 38, dates, and timestamps.
Nanosecond timestamps normalize to microseconds when exact. Unsupported types,
submicrosecond values, or a Parquet roundtrip that changes schema or values
raise an error. Cast deliberately in preparation code.

Reuse the same captured source to share one input. Separate `pm.data` calls
create separate capture origins. Give distinct captures distinct names.
`draft.inputs` exposes `pymalloy.authoring.Input` owners with names, row counts,
fingerprints, and detached Arrow values. `draft.text` retains logical input paths.
`ModelSource.inputs` carries those owners across runtime closure.

## Carry inputs into widgets and bundles

Pass a draft or snapshot directly to `pm.MalloyWidget`. The widget sends captured
Parquet as browser virtual files. Its browser compiler and engine use their own
runtime. Explicit `files=` entries cannot shadow managed names.
See [widgets](widget.md) for display and asynchronous readback.

`pymalloy.export.bundle(accepted, directory)` writes a validated model and its
captured inputs. A `ModelSource` also retains input owners and can be bundled.
Passing `Validation` additionally records validation outcomes and bindings.
Plain `Draft.save()` rejects captured inputs. See [source bundles](bundles.md).

`draft.to_python(inputs={"orders": "prepared"})` reconstructs grammar with an
explicit producer-variable binding. Keep the producing notebook or script for
the dataframe operations, external files, environment, and randomness needed to
rebuild the input. In a notebook, give preparation, construction, validation,
and export separate cells with direct variable references.

For result conversion and Arrow stream consumers, see
[read columnar results](running.md#read-columnar-results).
