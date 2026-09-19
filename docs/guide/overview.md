# What is PyMalloy?

PyMalloy lets you author, check, run, and share Malloy models from Python.
[Malloy](https://docs.malloydata.dev/documentation/) defines sources, joins,
measures, and queries, then compiles them to SQL. PyMalloy supplies Python
composition, runtime adapters, and exports. DuckDB executes the SQL.

## Choose a workflow

| Task                                       | Start here                                                         | What you get                                             |
| ------------------------------------------ | ------------------------------------------------------------------ | -------------------------------------------------------- |
| Create or extend a semantic model          | [Author and validate models](authoring.md)                         | Editable Python grammar and ordinary Malloy source       |
| Use a prepared dataframe                   | [Capture Python data](dataframes.md)                               | An immutable input that can travel with the model        |
| Run queries in a script or notebook kernel | [Run queries from Python](headless-python.md)                      | SQL, columns, and materialized values                    |
| Explore in Jupyter or marimo               | [Your first widget](getting-started.md)                            | Browser execution and asynchronous Python snapshots      |
| Share a model and its inputs               | [Bundle models and inputs](bundles.md)                             | Malloy files, copied data, a manifest, and replay script |
| Share an executable notebook               | [Export notebooks](export.md)                                      | marimo Python or Jupyter JSON                            |
| Use JavaScript                             | [Node](../reference/node.md) or [browser](../reference/browser.md) | A shared Model/Query/Result API                          |

## Choose dependencies

| Install              | Capabilities                                                                               |
| -------------------- | ------------------------------------------------------------------------------------------ |
| `pymalloy`           | Symbolic authoring, source snapshots, browser widgets, and installed agent guidance        |
| `pymalloy[headless]` | Adds Python-side parsing, checks, validation, native Arrow results, and export preparation |

The base package includes anywidget and agent-plugins. Widgets compile and
execute Malloy in the browser without Deno or native Python DuckDB. Their first
use downloads DuckDB WebAssembly and requires browser workers.

The `headless` extra adds the Deno compiler process, native DuckDB, PyArrow, and
timezone data. Headless execution works in scripts and notebook kernels without
a browser. It does not run an HTTP service.

Install `polars`, `marimo`, or your Jupyter host directly when using them.
`pm.data(frame)` requires PyArrow, which can also be installed directly for
Python-prepared data feeding browser widgets. Syntax construction starts neither
compiler nor data engine.

When embedding Python in a custom Pyodide host, load `micropip` and `lzma`
with `await pyodide.loadPackage(["micropip", "lzma"])`, then install
`pymalloy` through micropip. Pyodide ships `lzma` separately, and the included
agent-guidance reader needs it when imported.

Native Python, Node, and browser runtimes have separate connections. Use
[captured inputs](dataframes.md) or [virtual files](widget.md) to supply browser
data. Native database tables belong to their connection.

Read [concepts and boundaries](concepts.md) for the relationships between drafts,
models, snapshots, validation, and bundles. For language syntax and modeling
semantics, use the [Malloy documentation](https://docs.malloydata.dev/documentation/).
PyMalloy's runtime adapters execute the DuckDB dialect. `connection_name` on
Python models and `connectionName` on JavaScript sessions configure the Malloy
connection name. Models written for other databases need compatible sources and SQL.
