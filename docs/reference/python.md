# Python widget API

```python
from pymalloy import MalloyWidget

widget = MalloyWidget("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }")
widget
```

`MalloyWidget(source, *, files=None, query=None, givens=None, runtime=None,
connection_name="duckdb", auto_run=True)` creates an
anywidget for text, `Expr`, `Sort`, `Fragment`, `Draft`, `ModelSource`, native
`Model` or `Query`, and materialized `Result` values. `files`, `query`, `givens`,
`auto_run`, and `source` can be assigned after construction. Assign complete mappings to update
files or givens. `files`, `givens`, and `state` are recursively read-only mappings.
Nested sequences are tuples. Reads reuse the published snapshot, and retained
snapshots stay unchanged after later updates. `pymalloy.analysis.to_dict(value)`
creates editable dictionaries and lists when needed.

`state` contains `status`, `queries`, `sql`, `columns`, `rows`, `result`,
`inspection`, `diagnostics`, and `error`. Status is `idle`, `loading`, `ready`, `error`, or
`closed`. Observe `state` for asynchronous updates. Observers receive the same
immutable snapshot. `close()` is idempotent and releases the browser session. Native models and
connections remain owned by the caller.

`connection_name` chooses the Malloy connection served by the browser's DuckDB
runtime. It is read-only for the widget's lifetime and must match the connection
used by the source. Pass it explicitly for aliases such as `analytics`.

`ModelSource(url, text, imports, document_kind=None)` captures source independently
of data. Its kind is `"model"` or `"notebook"`, inferred from the URL when omitted.
The widget respects that kind when compiling the source.
`pymalloy.browser.Bundle(module, worker)` and
`Runtime(mvp, eh=None)` configure explicit DuckDB runtime URLs.
Use absolute HTTP(S) URLs with CORS and the notebook host's content-security
policy configured to allow them.

[Headless queries, models, and results](headless.md) are available with the
headless extra. The base install includes widgets and agent guidance. Malloy compilation and DuckDB
execution run in the browser, with no Deno dependency.

Set `auto_run=False` to require an explicit **Check model** or **Run query**
action. PyMalloy values displayed directly as cell outputs use this setting.
Check resolves the model and schemas, which can read data for schema discovery.
A native `Model` or `Query` offers **Preview 20 rows** using its existing
connection with a 30-second timeout. Materialized `Result` values show up to
20 retained rows. See [notebook editing](../guide/notebook-editing.md) for the
behavior of each value type.

For native `Model`, `Query`, and `Result` values, omit `files` and `runtime`:
their Python context supplies data access. A widget bound to a `Query` accepts
that query's name or `None`. Pass its `Model` to choose among the model's queries.

A `Draft` can carry `pm.data(frame)` inputs. MalloyWidget sends their captured
Parquet bytes as managed virtual files when compilation or execution is requested. This requires PyArrow, without the headless
extra or Deno. User `files` cannot shadow managed names. See the
[dataframe guide](../guide/dataframes.md).
