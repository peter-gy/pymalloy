# Export notebooks

Export a Malloy file as an executable [marimo](https://docs.marimo.io/) or
[Jupyter](https://docs.jupyter.org/) notebook.

For marimo:

```sh
pip install "pymalloy[server,marimo]"
```

Save this as `answer.malloy`:

```text
run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }
```

Export and open a marimo notebook:

```sh
pymalloy export answer.malloy --format marimo --output answer.py
marimo edit answer.py
```

For Jupyter, install `pymalloy[server,jupyter]` and run:

```sh
pymalloy export answer.malloy --format jupyter --output answer.ipynb
```

Open the export in Jupyter with its declared dependencies installed. Start the
kernel from the notebook's directory so relative data paths resolve correctly.

## Choose a profile

The profile determines how the notebook runs queries. Both formats support all three:

| Profile                 | Query execution                                   | Runtime dependencies |
| ----------------------- | ------------------------------------------------- | -------------------- |
| `precompiled` (default) | Fixed SQL, editable in the notebook               | DuckDB and Polars    |
| `native`                | Editable Malloy model returning Polars dataframes | `pymalloy[server]`   |
| `widget`                | Interactive browser widgets                       | `pymalloy`           |

The notebook records its runtime dependencies and also needs its notebook host.
`precompiled` runs without PyMalloy or its compiler. All profiles keep data
external to the notebook.

For a native model:

```sh
pymalloy export answer.malloy --profile native --format marimo --output answer.py
```

For a widget in each query cell:

```sh
pymalloy export answer.malloy --profile widget --format jupyter --output answer.ipynb
```

`native` and `widget` capture the full model and its imports, including queries
not selected as notebook cells. They pin PyMalloy to the exporting version.
Source files may be moved after export. Keep referenced data accessible.
See [data access](#preserve-data-access) for supported inputs.

All profiles compile selected queries and discover schemas during export.
`native` and `widget` load the captured source against current schemas again when
the notebook runs. This is called **hydration**.

Widget queries require a connected browser frontend. Headless Python execution
creates widgets but does not run their queries. The page must allow runtime
downloads and [browser workers](/guide/widget#host-duckdb-assets).

## Compile once, render twice

`compile_document()` prepares a document. Each renderer returns notebook text:

```python
from pathlib import Path
from pymalloy.exports import compile_document, marimo, jupyter

document = compile_document("answer.malloy", profile="native")

for renderer, filename in [(marimo, "/tmp/answer.py"), (jupyter, "/tmp/answer.ipynb")]:
    output = Path(filename)
    output.write_text(renderer.render(document, output_path=output), encoding="utf-8")
```

Both renderers use the document's profile and resolve data paths relative to
`output_path`. Identical inputs, schemas, options, output paths, and dependency
versions produce identical notebook bytes. See the [Document reference](/reference/export)
for cell types and fields.

## Work with a native model

Edit `model_source` to change Malloy definitions or captured imports, and `givens`
to change parameters. Query cells call `model.run()`. Add cells to discover queries,
inspect SQL, or run new Malloy:

```python
model.queries
model.inspect()
model.sql(query="run:1", givens=givens)
model.run("run: duckdb.sql('SELECT 84 AS answer') -> { select: answer }")
```

In marimo, source edits reload the model and rerun dependent cells. Given edits
rerun queries. In Jupyter, rerun the edited setup cells, then affected query cells.

Call `session.close()` when finished. Rerun setup to use the model again.
See the [native Python API](/reference/server) for model methods.

## Work with browser widgets

The `widget` notebook has `model_source`, `files`, and `givens` setup cells.
Each query cell displays a `Malloy` widget. In the generated `answer` notebook:

```python
run_1.query = "run:1"
run_1.state
```

The dropdown lists the full model's queries. `state` holds asynchronous results.
See [widget state](/reference/python#widget-state) for fields and observation.
A model with no queries produces an idle widget until source edits add one.

Edit `ModelSource`'s `text` or `imports` arguments in the setup cell to change
definitions. Marimo recreates widgets after setup edits. In Jupyter, rerun edited
setup cells and affected widget cells. Assign `query` or `givens` directly to
reuse a widget's compiled model. Call `run_1.close()` when finished.

## Execute Jupyter programmatically

[nbclient](https://nbclient.readthedocs.io/) executes Jupyter notebooks from Python.
Set its working directory to the exported notebook's parent:

```python
from pathlib import Path
import nbformat
from nbclient import NotebookClient

output = Path("/tmp/answer.ipynb")
notebook = nbformat.read(output, as_version=4)
NotebookClient(
    notebook,
    resources={"metadata": {"path": str(output.parent)}},
).execute()
```

The `jupyter` extra includes nbclient and a Python kernel. This executes
`precompiled` and `native` queries. Widget queries still need a browser frontend.

## Select queries

Repeat `--query` to select queries, or use `--query '*'` for all available queries:

```sh
pymalloy export answer.malloy --format marimo --query run:1 --output /tmp/answer.py
```

By default, `.malloy` exports run statements, otherwise named queries, otherwise
public source views.

For `.malloynb` or `.malloysql`, omit `--query` to preserve Markdown and cell
order. Explicit selectors omit Markdown and use selection order. `--query '*'`
uses query-list order, which may differ from document order. Preserve document
order when SQL cells depend on earlier writes.

## Set given values

Save this parameterized model as `filtered.malloy`:

```text
##! experimental.givens
given: minimum :: number
run: duckdb.sql('SELECT unnest([2, 12, 42]) AS value') -> {
  where: value >= $minimum
  select: value
}
```

Supply its required value when exporting:

```sh
pymalloy export filtered.malloy --format marimo \
  --givens '{"minimum": 20}' --output filtered.py
```

The notebook returns `42`. Python accepts `compile_document(..., givens={"minimum": 20})`.
Values apply to every selected query. `precompiled` embeds them in SQL, so export
again to change them. For `native` and `widget`, edit the notebook's `givens` cell.
See [givens](/guide/givens) for declarations and accepted values.

## Preserve data access

`--data-root` sets the directory for relative data paths. `--database` records an
existing DuckDB database, opened read-only. Keep data accessible when running the
notebook. Save registered Python data to files or persistent tables before export.

Document SQL cells accept one `SELECT` or `COPY`. `COPY` writes its destination
when the notebook runs. Rerunning a marimo `COPY` cell reruns following queries.
Sources referencing generated files still need their schemas during export.

With `precompiled`, each query opens and closes its own connection, including on
failure. Configure credentials and settings in the generated `connect()` context
manager. Results remain available after the connection closes.

With `native`, the model and queries share one session connection. Configure
`session.connection` before loading the model if schema discovery needs credentials
or settings. Both native and precompiled notebooks initialize DuckDB in UTC.

With `widget`, the `files` cell reads local files as bytes, preserving model file
names, including absolute paths and `../` references. Keep those files accessible
to Python. The browser reads HTTP(S) data directly, requiring
[CORS permission](/guide/widget#files-and-imports). Each widget owns a separate
browser database and worker.

After local data changes, rerun `files` setup and the affected widget cells.

The full captured model, including unselected queries, must use explicit local
files or HTTP(S) URLs. Widget export rejects native tables, `--database`, globs,
computed file-reader arguments, other URL schemes, and `COPY`. Use `native` or
`precompiled` for databases and `COPY`.

See [CLI flags](/reference/cli) and the [export API](/reference/export).
