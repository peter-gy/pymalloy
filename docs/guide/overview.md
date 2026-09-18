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
| Run queries in a script or notebook kernel | [Run queries from Python](server-python.md)                        | SQL, columns, and materialized values                    |
| Explore in Jupyter or marimo               | [Your first widget](getting-started.md)                            | Browser execution and asynchronous Python snapshots      |
| Share a model and its inputs               | [Bundle models and inputs](bundles.md)                             | Malloy files, copied data, a manifest, and replay script |
| Share an executable notebook               | [Export notebooks](export.md)                                      | marimo Python or Jupyter JSON                            |
| Use JavaScript                             | [Node](../reference/node.md) or [browser](../reference/browser.md) | A shared Model/Query/Result API                          |

## Choose dependencies

| Install                       | Capabilities                                                            |
| ----------------------------- | ----------------------------------------------------------------------- |
| `pymalloy`                    | Python syntax construction and source records                           |
| `pymalloy[widget]`            | Browser widgets in Jupyter or marimo                                    |
| `pymalloy[agent]`             | Installed model-authoring guidance and agent discovery                  |
| `pymalloy[server]`            | Parse, check, validate, execute to Arrow in Python, and prepare exports |
| `pymalloy[dataframes]`        | Capture dataframe inputs and convert results with PyArrow and Polars    |
| `pymalloy[server,dataframes]` | Native execution with Polars input and result conversion                |

The `server` extra supplies the Deno compiler process and native DuckDB.
Widgets compile and execute in the browser, independently of that extra. Their
first use downloads DuckDB WebAssembly and requires browser workers. Python
syntax construction alone starts neither runtime.

Native Python, Node, and browser runtimes have separate connections. Use
[captured inputs](dataframes.md) or [virtual files](widget.md) to supply browser
data. Native database tables belong to their connection.

Read [concepts and boundaries](concepts.md) for the relationships between drafts,
models, snapshots, validation, and bundles. For language syntax and modeling
semantics, use the [Malloy documentation](https://docs.malloydata.dev/documentation/).
PyMalloy's runtime adapters execute the DuckDB dialect. `connection_name` on
Python models and `connectionName` on JavaScript sessions configure the Malloy
connection name. Models written for other databases need compatible sources and SQL.
