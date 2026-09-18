# Python widget API

```python
from pymalloy import Malloy
```

`Malloy` executes models in the browser through [anywidget](https://anywidget.dev/).
It requires a connected notebook frontend. Display it to see query choices and
results. Views of one widget share selection and results. See
[Getting started](/guide/getting-started) for installation and browser requirements.

## `Malloy`

```text
Malloy(source, *, files=None, query=None, givens=None, runtime=None)
```

| Argument  | Contract                                                                                                           |
| --------- | ------------------------------------------------------------------------------------------------------------------ |
| `source`  | Malloy source text or a [`ModelSource`](#modelsource) snapshot. Required. Empty text leaves the widget idle.       |
| `files`   | Mapping from virtual file names to UTF-8 text, `bytes`, or `{"url": "https://..."}`. Defaults to an empty mapping. |
| `query`   | Query selector or `None` for the model's default query.                                                            |
| `givens`  | Mapping of typed query values. Defaults to an empty mapping.                                                       |
| `runtime` | Immutable `pymalloy.browser.Runtime`, or `None` for default versioned jsDelivr assets.                             |

File descriptors accept absolute HTTP and HTTPS URLs. Remote servers must allow
browser requests. For source text, model imports resolve from `files`, relative
to the importing model's virtual path. A `ModelSource` supplies captured imports
by absolute URL and preserves the root URL for source locations. Its data files
still come from `files` or browser-accessible URLs.

Givens accept finite JSON-shaped values: strings, booleans, integers, floats,
`None`, lists, and mappings with string keys. Python integers preserve their
value when sent to Malloy. Invalid input raises `traitlets.TraitError`.

## Update a query

Assign `widget.source`, `widget.files`, `widget.query`, or `widget.givens` to rerun
the widget. Replace complete mappings for files and givens. The browser selector also updates `widget.query`.
Source and file changes reload the model. Query and given changes reuse it.
Pending updates coalesce while the current operation finishes. Equal assignments
leave inputs unchanged.

Selectors include named queries, exported `source.view` names, and one-based
`run:N` names. `query=None` executes the final run statement or a single available
query. Select a name when the model has several choices and no run statement.

Assignment validates Python types before publishing an update. File access,
compilation, selection, and execution happen asynchronously in the browser.
Their failures appear in `widget.state`.

## `ModelSource`

```python
from pymalloy import Malloy, ModelSource

source = ModelSource(
    url="memory://example/answer.malloy",
    text="import 'base.malloy'\nrun: numbers -> { select: value }",
    imports={
        "memory://example/base.malloy": "source: numbers is duckdb.sql('SELECT 42 AS value')",
    },
)
answer = Malloy(source)
answer
```

`ModelSource(url, text, imports={})` captures source immutably. `url` is the absolute
root URL, `text` its source, and `imports` maps absolute URLs to imported source.
Construction copies the mapping and exposes it read-only. Invalid URLs or import
values raise `ValueError`. Non-string root text raises `TypeError`.

Pass it to `Malloy` or [`session.load_source()`](/reference/server#session-load-source-source).
The runtime supplies data access and discovers current schemas. Missing captured
imports fail compilation.

Native and widget exports expose `document.source`. To edit notebook definitions,
replace the setup cell's `ModelSource` with updated `text` or `imports`.

## `widget.state`

Returns a detached dictionary containing the latest result:

| Key           | Value                                             |
| ------------- | ------------------------------------------------- |
| `status`      | `idle`, `loading`, `ready`, `error`, or `closed`. |
| `queries`     | List of available query selector strings.         |
| `sql`         | Compiled SQL string, or `None`.                   |
| `columns`     | List of result column names.                      |
| `rows`        | Complete result as a list of row dictionaries.    |
| `error`       | Failure message, or `None`.                       |
| `diagnostics` | List of compiler diagnostic dictionaries.         |

`state` is read-only and detached. Input changes clear it. Results from earlier
inputs cannot replace the current state.

Integer results become Python `int` values, including large integers. Nested
results retain lists and dictionaries. Dates and timestamps arrive as ISO strings
with millisecond precision, and decimal values arrive as strings. Nulls become
`None`. Non-finite numeric results become Python `float` values for NaN and
infinity. Binary values become lists of byte integers. Maps become lists of
`{"key": ..., "value": ...}` entries.

### Status

| Status    | Meaning                                                                    |
| --------- | -------------------------------------------------------------------------- |
| `idle`    | Waiting for browser initialization, nonempty source, or a query selection. |
| `loading` | Compiling the model or executing its query in the browser.                 |
| `ready`   | The current input produced a complete result.                              |
| `error`   | The current input failed. Inspect `error` and `diagnostics`.               |
| `closed`  | The widget has been closed. Create a new widget to run again.              |

Query choices survive execution failures. Correcting input clears diagnostics.

### Diagnostics

Compiler diagnostics contain:

| Key                 | Value                                                      |
| ------------------- | ---------------------------------------------------------- |
| `code`              | Malloy diagnostic identifier.                              |
| `severity`          | `error`, `warning`, or `debug`.                            |
| `message`           | Human-readable explanation.                                |
| `location`          | `None` or a dictionary with `url` and `range`.             |
| `replacement`       | Suggested source text for the diagnostic range, or `None`. |
| `data`, `error_tag` | Compiler context, or `None`.                               |

`range` has `start` and `end` positions, each with zero-based `line` and
`character` offsets. Characters count Unicode code points, and the end is
exclusive. Preserve the location URL when interpreting a message from an
imported model. The widget displays line and character positions starting at one.

Warnings can accompany success. Database and network failures may report `error`
with no diagnostics. Use [language tools](/guide/language-tools) to check models
in native Python before execution.

### Observe asynchronous results

```python
query = Malloy("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }")

def completed(change):
    if change["new"]["status"] == "ready":
        print(change["new"]["rows"])

query.observe(completed, names="state")
completed({"new": query.state})
query
```

The callback prints `[{'answer': 42}]`. Checking `query.state` also catches results
that arrived before registration. Remove the observer with
`query.unobserve(completed, names="state")` when finished. Its snapshots are detached.

The table previews 100 rows. `state["rows"]` holds the complete result. Limit
Malloy queries to fit browser memory and notebook connection capacity.

## `widget.close()`

Close the widget and release its browser connection and worker. The final state
has status `closed` and empty result fields. Repeated calls are safe. Changing an
input after closure raises `traitlets.TraitError`.

## Browser runtime

```python
from pymalloy import browser
```

`browser.Bundle(module: str, worker: str)` describes absolute HTTP or HTTPS URLs
for a matching DuckDB WebAssembly module and browser worker. Invalid URL types
raise `TypeError`. Invalid URLs raise `ValueError`.

`browser.Runtime(mvp: browser.Bundle, eh: browser.Bundle | None = None)` selects
widget assets. `mvp` is the baseline WebAssembly bundle. Optional `eh` provides
exception handling in supporting browsers. Include both to match the default
runtime. Nested queries require `eh` and a supporting browser.
Both records are frozen dataclasses. `widget.runtime` is read-only. Create a new
widget to change assets.

Use assets from `@duckdb/duckdb-wasm` version `1.33.1-dev57.0`. Requests
must satisfy the asset host's CORS rules and the notebook page's content security
policy. The page must permit `blob:` workers. See [hosting assets](/guide/widget#host-duckdb-assets)
for configuration.
