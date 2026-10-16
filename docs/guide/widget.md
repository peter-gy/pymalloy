# Show and update a widget

`MalloyWidget` runs [Malloy](https://docs.malloydata.dev/) queries in a notebook
browser using [DuckDB WebAssembly](https://duckdb.org/docs/stable/clients/wasm/overview.html),
a browser build of the SQL engine. For a browser-hosted Python kernel, follow
[browser Python setup](browser-python.md). In a native Python kernel, install:

```sh
pip install pymalloy
```

Display it in [Jupyter](https://docs.jupyter.org/), a notebook host, or
[marimo](https://docs.marimo.io/), a reactive Python notebook editor.
The widget uses [anywidget](https://anywidget.dev/), which connects Python
widgets to notebook browsers. First use downloads versioned DuckDB assets from
jsDelivr. The page must permit those downloads and browser workers.

```python
import pymalloy as pm

widget = pm.MalloyWidget(
    "run: duckdb.table('orders.csv') -> { aggregate: total is amount.sum() }",
    files={"orders.csv": "amount\n20\n22\n"},
)
widget
```

The displayed table shows total `42`. Execution starts after a browser attaches.
Open **SQL** to inspect the generated query. `files` registers virtual names with
UTF-8 text, bytes, or `{"url": "https://..."}` descriptors. Remote servers must
permit cross-origin resource sharing (CORS).

## Update inputs and consume results

```python
import pymalloy as pm
from pymalloy.analysis import to_dict

widget = pm.MalloyWidget(
    "run: duckdb.table('orders.csv') -> { aggregate: total is amount.sum() }",
    files={"orders.csv": "amount\n20\n22\n"},
)

def receive_result(change):
    state = change["new"]
    if state["status"] == "ready":
        print(to_dict(state["rows"]))

widget.observe(receive_result, names="state")
widget.files = {**widget.files, "orders.csv": "amount\n50\n75\n"}
widget
```

After display, the callback prints `[{'total': Decimal('125')}]`.
Assign `source`, `query`, `givens`, or `files` to request a revision.
Mappings are read-only, so assign a complete mapping to publish changes.
Observe `state` for asynchronous results and read rows when status is `ready`.

`state` contains query descriptors, SQL, columns, rows, the Malloy result tree,
inspection, diagnostics, and an error message. Nested mappings are read-only and
sequences are tuples. Retained snapshots stay unchanged after updates.
`to_dict` creates mutable containers and preserves scalar types such as `Decimal`.
Use an appropriate encoder if serializing those values as JSON.

Changing inputs cancels superseded work. Late results cannot replace the current
revision. Call `widget.close()` when finished. For explicit Check and Run controls,
construct with `auto_run=False`.

## Choose source and runtime assets

`source` accepts text, a `Draft`, or `ModelSource`, including captured Python
inputs. Authored values, native and browser models, queries, and results also
have [notebook inspectors](notebook-editing.md). Compiled models and queries use
their existing connection. Omit `files` and `runtime` when supplying one of these
values or a materialized result.

The Malloy connection name defaults to `duckdb`. For an `analytics` source, pass
`connection_name="analytics"`. It stays fixed for the widget's lifetime.

`pymalloy.browser.Bundle(module, worker)` and `Runtime(mvp, eh=None)` configure
absolute HTTP(S) URLs for matching WebAssembly modules and workers. Their servers
must permit CORS and the notebook host's content security policy must allow them.
See the [widget reference](../reference/widget.md) for signatures and state fields.

If frontend assets fail, inspect `widget.bundle_status`. Packaged JavaScript
travels through anywidget's notebook communication channel. `widget.state`
reports model compilation and query execution failures.

## Browser Python

[Pyodide](https://pyodide.org/en/stable/) runs Python in a browser. The browser
wheel includes Python authoring, widgets, and an asynchronous query API over the
browser runtime. Follow [browser Python setup](browser-python.md) to install the
wheel in a compatible notebook host, display a widget, or execute queries directly.
