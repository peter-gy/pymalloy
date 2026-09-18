# What is PyMalloy?

PyMalloy runs [Malloy](https://docs.malloydata.dev/documentation/) analyses in
notebooks, Python, and JavaScript. Malloy defines datasets and reusable queries,
then compiles them to SQL. [DuckDB](https://duckdb.org/) executes that SQL.

## Choose where to run

| Task                                   | Use                                      | Result                                        |
| -------------------------------------- | ---------------------------------------- | --------------------------------------------- |
| Explore in Jupyter or marimo           | [MalloyWidget](/guide/getting-started)   | Interactive table and Python result snapshots |
| Query files, dataframes, or a database | [Server Python](/guide/server-python)    | Result with optional dataframe conversion     |
| Share an executable analysis           | [Notebook export](/guide/export)         | marimo `.py` or Jupyter `.ipynb`              |
| Build a web application                | [Browser JavaScript](/reference/browser) | Rows, columns, and SQL                        |
| Query from Node                        | [Node](/reference/node)                  | Rows, columns, SQL, and Malloy metadata       |

**Native execution** uses DuckDB in Python or Node. Browser execution uses
WebAssembly, compiled database code running in a background browser worker.
These environments have separate connections. To use Python data in a widget,
supply a file the browser can read.

## Explore in a notebook

Install `pymalloy` and display a `MalloyWidget`. Select queries, change parameters,
and inspect SQL. Malloy's renderer displays nested tables and chart tags, while
`widget.state` receives the complete result asynchronously. First use downloads DuckDB WebAssembly and needs
permission to create browser workers.

[Run your first widget query](/guide/getting-started).

## Run from Python

Install `pymalloy[server,dataframes]` and call `pymalloy.run` or `pymalloy.model` to query files,
dataframes, or a DuckDB connection. Queries return `Result` objects with rows,
SQL, and optional Arrow or Polars conversion. Python executes queries locally and owns a Deno compiler process.

[Run a server-side Python query](/guide/server-python).

## Share a notebook

Export a Malloy file as marimo or Jupyter. Choose `precompiled` for SQL that runs
without PyMalloy, `server` for an editable Python model, or `widget` for browser
widgets. Recipients need the notebook's dependencies and referenced data.

[Export a notebook](/guide/export).

## Learn Malloy

The [concepts guide](/guide/concepts) defines PyMalloy's terms. For modeling syntax,
joins, and nested queries, use the [Malloy documentation](https://docs.malloydata.dev/documentation/).
PyMalloy uses the `duckdb` connection. Adapt models written for other databases
before running them.
