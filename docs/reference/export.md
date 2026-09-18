# Export API

Compile a local Malloy file into a `Document`, then render a marimo or Jupyter
notebook. See [Export notebooks](/guide/export) for the workflow.

Install `pymalloy[server]` for compilation. Add `marimo` to render marimo notebooks,
or `jupyter` to execute Jupyter notebooks:

```sh
pip install "pymalloy[server,marimo,jupyter]"
```

```python
from pymalloy.exports import compile_document, marimo, jupyter
```

## `compile_document(model, *, profile="precompiled", queries=(), givens=None, data_root=None, database=None, title=None, timeout=120)`

Return an immutable `Document` with ordered cells and an execution profile.
`model` is a string or `Path` to a `.malloy`, `.malloynb`, or `.malloysql` file.
Compilation reads imports and discovers schemas. Queries execute in the notebook.

| Argument    | Behavior                                                                                                                             |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `profile`   | `"precompiled"` (default) for standalone SQL, `"native"` for a hydrated Python model, or `"widget"` for interactive browser widgets. |
| `queries`   | Sequence of selectors, default `()`. See [Query selection](#query-selection).                                                        |
| `givens`    | Mapping of declared given names to values for this export. Defaults to `None`.                                                       |
| `data_root` | Directory for relative data paths. Defaults to the model's directory.                                                                |
| `database`  | Existing DuckDB database file, opened read-only for schema discovery.                                                                |
| `title`     | Document title. Defaults to the title-cased model filename stem.                                                                     |
| `timeout`   | Positive operation budget in seconds. Defaults to `120`.                                                                             |

Compilation closes its session and connection before returning. Data files and
databases must remain accessible when the notebook runs. Save registered Python
data to a file or persistent database table before exporting.

`givens` accepts [native Python values](/guide/givens#choose-values) for every
selected Malloy query, including those embedded in SQL cells. Omitted values use
declared defaults. Required givens need a value. Precompiled SQL captures resolved
values. Native and widget notebooks pass an editable `givens` mapping to each
query. Normalization preserves integers, converts tuples to lists, and stores
dates, datetimes, and decimals as strings.

All profiles compile selected queries during export. `native` and `widget`
capture the root source and recursive imports, including unselected definitions.
Loading the native model or widget discovers current schemas. Data remains external.

`widget` captures local file references throughout the model, including unselected
queries and document SQL. Notebook setup reads those files into bytes for the
browser. The browser reads HTTP and HTTPS data URLs directly, requiring CORS.
Widget export rejects `database`, native database tables, `COPY`, globs, computed
file-reader arguments, and non-HTTP URL schemes.

Missing files, invalid selectors, schema failures, language errors, and operation
timeouts raise `pymalloy.server.CompilationError`. An unknown profile raises
`ValueError` before compilation.

### Query selection

A selector identifies an executable query:

| Selector           | Selects                                                               |
| ------------------ | --------------------------------------------------------------------- |
| `summary`          | A named query.                                                        |
| `orders.by_region` | A named view on an exported source.                                   |
| `run:1`            | The first unnamed `run:` statement. Numbering starts at 1.            |
| `sql:1`            | The first SQL cell in a Malloy document. Numbering starts at 1.       |
| `*`                | Every available run, named query, exported source view, and SQL cell. |

For `.malloy` files, the default chooses run statements if present, otherwise
named queries, otherwise exported source views. A source-only model produces a
Markdown inventory of its exported sources. The `widget` profile also displays a
widget for a source-only model. Each selected widget starts on that query and
retains the full model's query selector.

For `.malloynb` and `.malloysql` documents, the default preserves authored
Markdown and executable cell order. Explicit selectors produce query cells in
the supplied order and omit authored Markdown. `['*']` uses the available-query
order and must appear alone. Include any required `COPY` cells before queries
that read their output.

## `Document(title, cells, data_root, database=None, source=None, profile="precompiled")`

Immutable export value:

| Field       | Type and meaning                                                                                                                            |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `title`     | `str`, used for a generated heading and Jupyter title metadata. An initial Markdown cell supplies the notebook's introduction when present. |
| `cells`     | `tuple[Markdown \| Query, ...]`, in execution and display order.                                                                            |
| `data_root` | `Path`, the directory used for relative data references.                                                                                    |
| `database`  | `Path \| None`, an existing DuckDB database opened read-only by the notebook.                                                               |
| `source`    | `ModelSource \| None`, captured model text and imports, required for `native` and `widget`. Precompiled documents have no captured source.  |
| `profile`   | `"precompiled"`, `"native"`, or `"widget"`. Defaults to `"precompiled"`.                                                                    |
| `givens`    | Read-only property returning a detached dictionary of normalized overrides for the hydrated model. Empty for precompiled documents.         |
| `queries`   | Read-only property returning the `Query` cells as a tuple.                                                                                  |

`Markdown(text)` contains Markdown. `Query(name, sql, kind)` contains a label,
one DuckDB statement, and kind `"select"` or `"copy"`, which controls result handling
and execution order. `COPY` writes when the notebook runs. A source reading its
output still needs the file's schema during compilation.

Construct a precompiled document directly to render SQL you already have:

```python
from pathlib import Path
from pymalloy.exports import Document, Markdown, Query

document = Document(
    title="Answer",
    cells=(Markdown("# Answer"), Query("answer", "SELECT 42 AS answer", "select")),
    data_root=Path.cwd(),
)
```

Records and the Jupyter renderer require the base package. The marimo renderer
loads marimo when called. Direct construction requires valid single-statement
SQL, its matching kind, and `Path` values. Invalid kinds raise `ValueError`.
Renderers preserve SQL. For file access, use
absolute paths or expressions such as
`read_parquet(getvariable('data_root') || '/orders.parquet')`.

## `marimo.render(document, *, output_path)`

Return marimo Python source. `output_path`, a string or `Path`, determines paths
from the notebook to its data and database. Write the returned string there.

Precompiled cells use `mo.sql`, native cells use `model.run()`, and both return
Polars dataframes. Widget cells create and display `Malloy` instances.
Precompiled and native `COPY` cells write and return empty dataframes. Dependent
queries run after the write and rerun with it. Script metadata declares marimo plus DuckDB and
Polars for `precompiled`, `pymalloy[server]` for `native`, or `pymalloy` for `widget`.
PyMalloy dependencies are pinned to the exporting version.
Data paths resolve from `mo.notebook_dir()` when the notebook executes.

## `jupyter.render(document, *, output_path)`

Return Jupyter notebook 4.5 JSON with deterministic cell IDs and empty outputs.
`output_path` determines relative data paths. Write the returned string there.

Run the kernel from the notebook's directory and execute cells in order.
Precompiled exports need DuckDB and Polars. Native exports need `pymalloy[server]`
and widget exports need `pymalloy`, pinned to the exporting version.
Precompiled and native query cells return Polars dataframes. Their `COPY` cells
write and return empty dataframes. Widget queries require a connected frontend.
The `jupyter` extra supplies notebook validation, execution, and a Python kernel.

`metadata.pymalloy` records `profile` and `dependencies`. Install these dependencies
before running the notebook.

Both formats configure DuckDB's timezone as UTC. Keep the notebook's relative
layout with its data when moving the export. Matching inputs, schemas, options,
output path, and dependency versions produce matching notebook bytes.

## Generated Python values

Each query result is assigned to a Python variable. A selector such as
`orders.by_region` becomes `orders_by_region`. Punctuation becomes underscores,
leading and trailing underscores are trimmed, and empty labels become `result`.
Labels starting with a digit or matching a Python keyword receive a `result_`
prefix. Name collisions receive suffixes starting at `_2`. Setup names
`Path`, `mo`, `duckdb`, `pl`, `contextmanager`, `connect`, `connection`, `data_root`,
`database`, `ModelSource`, `Session`, `Malloy`, `model_source`, `session`, `model`,
`files`, `givens`, `BaseException`, and `str` are reserved.

### Precompiled profile

Generated `connect()` opens DuckDB, configures data access, and closes the
connection after each query materializes its dataframe or fails. Persistent
databases open read-only. Use it for additional Python queries:

```python
with connect() as connection:
    answer = connection.execute("SELECT 42 AS answer").fetchone()
```

Configure shared DuckDB settings in `connect()`. Marimo reruns dependent queries
when setup reruns. In Jupyter, rerun setup and affected cells.

### Native profile

| Value          | Contract                                                                                                                                                |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `model_source` | [`pymalloy.ModelSource`](/reference/python#modelsource) containing root `text` and an `imports` mapping. Edit its source strings to change definitions. |
| `givens`       | Dictionary of supplied overrides, normalized to Malloy given values. Edit or replace it to change query inputs.                                         |
| `session`      | Native session owning the notebook's DuckDB connection and compiler process.                                                                            |
| `model`        | Retained model loaded with `session.load_source(model_source)`.                                                                                         |

Selected query cells call `model.run(query=..., givens=givens)`. The full model
supports `model.queries`, `model.inspect()`, `model.sql()`, and new query source
through `model.run(source)`. See the [native Python API](/reference/server).

Marimo reruns model setup when source or data configuration changes, and queries
when `givens` changes. In Jupyter, rerun edited setup and affected queries.
Replaced sessions release resources when no references remain. Retaining a model
retains its session. Call `session.close()` for immediate cleanup. Results remain available.

### Widget profile

`model_source` and `givens` match the native profile. `files` maps model file names
to bytes read from local data during setup. Root and import URLs preserve their
identities for relative imports and diagnostics.

Each query variable holds `Malloy(model_source, files=files, query=..., givens=givens)`
with the full model's query choices. Results arrive asynchronously in `state`.
See the [Python widget API](/reference/python) for input assignment, observation,
and `close()`.

Marimo recreates widgets when their setup inputs change. In Jupyter, rerun the
edited setup and affected widget cells. Direct changes to a widget's `query` or
`givens` reuse its compiled model. Each widget owns its browser database and
worker. The browser loads DuckDB assets and must be able to access remote data
URLs under CORS rules.
