# Python widget API

```python
from pymalloy import MalloyWidget

widget = MalloyWidget("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }")
widget
```

`MalloyWidget(source, *, files=None, query=None, givens=None, runtime=None,
connection_name="duckdb")` creates an
anywidget whose browser runtime starts when a notebook initializes it. Source is text, `ModelSource`, or `Draft`. `files`, `query`, `givens`, and
`source` can be assigned after construction. Assign complete mappings to update
files or givens. `files`, `givens`, and `state` are recursively read-only mappings.
Nested sequences are tuples. Reads reuse the published snapshot, and retained
snapshots stay unchanged after later updates. `pymalloy.analysis.to_dict(value)`
creates editable dictionaries and lists when needed.

`state` contains `status`, `queries`, `sql`, `columns`, `rows`, `result`,
`diagnostics`, and `error`. Status is `idle`, `loading`, `ready`, `error`, or
`closed`. Observe `state` for asynchronous updates. Observers receive the same
immutable snapshot. `close()` is idempotent and releases the browser session.

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

[Server queries, models, and results](server.md) are available with the
server extra. Install `pymalloy[widget]` for widgets. Malloy compilation and DuckDB
execution run in the browser, with no Deno dependency.

A `Draft` can carry `pm.data(frame)` inputs. MalloyWidget sends their captured
Parquet bytes as managed virtual files. This requires PyArrow, without the server
extra or Deno. User `files` cannot shadow managed names. See the
[dataframe guide](../guide/dataframes.md).
