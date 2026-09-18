# Python widget API

```python
from pymalloy import MalloyWidget

widget = MalloyWidget("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }")
widget
```

`MalloyWidget(source, *, files=None, query=None, givens=None, runtime=None)` creates an
anywidget view. Source is text or `ModelSource`. `files`, `query`, `givens`, and
`source` can be assigned after construction. Assign complete mappings to update
files or givens. Returned mappings and state are detached snapshots.

`state` contains status, query descriptors, SQL, columns, rows, the typed Malloy
result, diagnostics, and an error message. Status is `idle`, `loading`, `ready`,
`error`, or `closed`. Observe `state` for asynchronous updates. `close()` is
idempotent and releases the browser session.

`ModelSource(url, text, imports)` captures source independently of data.
`pymalloy.browser.Bundle(module, worker)` and
`Runtime(mvp, eh=None)` configure explicit DuckDB runtime URLs.
Use absolute HTTP(S) URLs with CORS and the notebook host's content-security
policy configured to allow them.

[Server queries, models, and results](server.md) are available with the
server extra. `pip install pymalloy` is sufficient for widgets: Malloy compilation
and DuckDB execution run in the browser, with no Deno dependency or extra.
