# Troubleshooting

Find the symptom, then check its inputs and execution environment.

## The widget stays idle or never appears

Widget execution needs a connected notebook frontend. Display the object:

```python
from pymalloy import Malloy

query = Malloy("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }")
query
```

Empty source or a model with no queries stays idle. Add `run:` or select a
public view. In Jupyter, trust the notebook and enable widget rendering.

First use downloads DuckDB WebAssembly and workers from jsDelivr. Check the
browser console for blocked requests or workers. To host assets yourself, configure
[widget assets](/guide/widget#host-duckdb-assets) or [browser bundles](/reference/browser).

## Python results are empty immediately after display

Results arrive asynchronously. Observe `ready` and check the current snapshot
in case the result already arrived:

```python
def completed(change):
    state = change["new"]
    if state["status"] == "ready":
        print(state["rows"])

query.observe(completed, names="state")
completed({"new": query.state})
query
```

Input changes clear the previous result. Assign complete `files` or `givens`
dictionaries to notify the browser. Use [native Python](/guide/native-python)
for synchronous results.

## A file or imported model cannot be found

For widgets, supply text or bytes under the file name used in Malloy. Remote
URLs require CORS permission. See [widget files](/guide/widget#files-and-imports).

For native sessions, local imports resolve beside the model. Data paths use
`data_root` (Python) or `dataRoot` (Node), defaulting to the loaded model's directory
or the inline model's base directory.
DuckDB reads remote data using its extensions and credentials. See
[data paths](/guide/data#resolve-data-paths).

## A query selector is rejected

Use an exact entry from `model.queries` or `widget.state["queries"]`.
With several queries and no `run:`, a selector is required. Rename conflicting
queries or views if loading reports ambiguous names. See [query selection](/guide/models#select-a-query).

## A changed table still has the old schema

A model captures schemas when loaded. Reload after changing columns, types, or
imports. New rows are visible on the next run. See [schema refresh](/guide/models#keep-schemas-current).

For widgets, replace `source` or `files`. Query and given changes reuse the model.
For remote data, use a versioned URL or a new widget to avoid cached content.

## A check succeeds but a document SQL cell fails

`Session.check()` validates Malloy, including embedded expressions, but standalone
SQL needs DuckDB validation. Inspect a cell with `model.sql(query="sql:1")`.
Executing `COPY` writes its destination.

For compiler errors, inspect the diagnostic's code, message, URL, and range.
Native Python reports use [analysis records](/reference/analysis). Widget reports
use [`state["diagnostics"]`](/reference/python#widget-state).

## A session or model is closed

Closing a session invalidates its retained models. Create a new session after its
native Python compiler process fails, an active operation times out, or its browser
worker fails. Ordinary compilation and query errors leave sessions available for
another call, subject to DuckDB's transaction rollback requirements.

A closed widget rejects new inputs. Create a new `Malloy(...)` object. See the
[Python session lifecycle](/reference/server#timeouts-and-concurrency) and
[browser lifecycle](/reference/browser#session-close) for the affected runtime.

## An exported notebook cannot access its data

Keep files, tables, extensions, and credentials available to the notebook.
Save Python data and temporary tables to files or persistent tables before export.

Start Jupyter kernels in the notebook's directory, or set nbclient's working
directory explicitly. Render with the actual output path to resolve data paths.
See [export data access](/guide/export#preserve-data-access).

For `COPY` cells, omit query selectors to preserve document order and ensure
destinations are writable. Rerunning a marimo write cell reruns following queries.
