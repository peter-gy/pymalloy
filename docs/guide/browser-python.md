# Run Python in the browser

[Pyodide](https://pyodide.org/en/stable/) runs Python in a browser. PyMalloy's
browser wheel provides Python authoring, notebook widgets, and asynchronous
queries using [DuckDB WebAssembly](https://duckdb.org/docs/stable/clients/wasm/overview.html),
a SQL engine running in a browser worker. Standalone Pyodide and JupyterLite
use the tested **314.0.7** runtime with Python **3.14.2**. The marimo WebAssembly
host selects its compatible runtime as described in [notebook hosts](#notebook-hosts).

## Install in a browser notebook

Use a notebook host with Pyodide and [anywidget](https://anywidget.dev/) support.
Anywidget synchronizes Python widget state with browser views. Install the
package in a Python cell with
[micropip](https://micropip.pyodide.org/), Pyodide's package installer:

<!-- not-executed -->

```python
import micropip

await micropip.install("pymalloy")
```

Micropip selects the `py3-none-any` browser wheel. Python packages, widget assets,
and the versioned DuckDB modules and workers need network access. Remote data
servers must permit [cross-origin resource sharing](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS),
which lets the notebook's origin read their responses. The host's content
security policy must permit the modules and browser workers.

## Notebook hosts

[JupyterLite](https://jupyterlite.readthedocs.io/) hosts Jupyter notebooks and
Python kernels in the browser. [marimo WebAssembly](https://docs.marimo.io/guides/wasm/)
runs reactive Python notebooks in the browser. Both display PyMalloy through
their anywidget integration.

| Host                                        | Tested Pyodide runtime |
| ------------------------------------------- | ---------------------- |
| JupyterLite 0.8.6 with Pyodide kernel 0.8.6 | 314.0.7                |
| marimo 0.25.1 WebAssembly export            | 314.0.0                |

Select the host's listed runtime when deploying a notebook. The browser wheel
is the same artifact for each host. For a custom Pyodide page, load `micropip`
with `await pyodide.loadPackage("micropip")` before executing the Python install
cell. A custom page also needs an anywidget manager to display widgets. Direct
asynchronous query execution uses the browser API independently of a widget
manager.

## Display a widget

<!-- not-executed -->

```python
import pymalloy as pm

widget = pm.MalloyWidget(
    "run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }"
)
widget
```

The notebook displays a table containing `answer: 42`. Execution starts when the
host attaches a browser view. Observe `widget.state` for completed rows and
errors, assign inputs to request another run, and call `widget.close()` when
finished. The [widget guide](widget.md) covers files and asynchronous readback.

## Execute a query directly

The `browser` module executes queries independently of a displayed widget.
Opening the first connection loads the packaged JavaScript runtime through
Pyodide's
[`run_js`](https://pyodide.org/en/stable/usage/api/python-api/code.html#pyodide.code.run_js),
which evaluates JavaScript strings. A custom host's content security policy must
permit that evaluation in the Python worker, along with WebAssembly loading,
asset fetches, and creation of DuckDB workers from `blob:` URLs.

<!-- not-executed -->

```python
from pymalloy import browser

async with browser.connect(timeout=30) as connection:
    model = await connection.model(
        "query: answer is duckdb.sql('SELECT 42 AS answer') -> { select: answer }"
    )
    result = await model.query("answer").run()

print(result.to_pylist())
```

The result is `[{'answer': 42}]`. The connection owns a DuckDB worker. Compilation,
SQL preparation, and execution are asynchronous. Leaving `async with` closes the
connection and its models. Materialized results remain readable after closure.

Use the same immutable Python constructors to build a `Draft`, then pass it to
`await connection.model(draft)`. Browser queries preserve integers, decimal
values, and nested rows when converting to Python. Results contain
materialized Python values. See the [browser Python reference](../reference/browser-python.md)
for query selection, tooling, files, and lifetime.

## Supply files

Pass file bytes under the names used in the model:

<!-- not-executed -->

```python
from pymalloy import browser

async with browser.connect() as connection:
    model = await connection.model(
        "run: duckdb.table('orders.csv') -> { select: amount }",
        files={"orders.csv": b"amount\n20\n22\n"},
    )
    rows = (await model.query().run()).to_pylist()

print(rows)
```

The result is `[{'amount': 20}, {'amount': 22}]`. A file mapping value can also be
an absolute HTTP(S) URL or a `pathlib.Path` in Pyodide's virtual filesystem.
Compilation captures local file bytes. Imports use the model's URL and the
supplied source files. Loading a model with a `Path` reads its root text. Supply
data and imported files explicitly in `files`. Recompile after changing source or
schema. A compiled model retains its file snapshot.

Widget `files` also accept UTF-8 text and `{"url": "https://..."}` descriptors.
Browser connection `files` use bytes, paths, or URL strings. Choose the shape
for the API receiving the files.
