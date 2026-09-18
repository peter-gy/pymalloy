# Export notebooks

Compile a Malloy model or document, then choose a notebook format:

```sh
pip install 'pymalloy[server,dataframes,marimo,jupyter]'
pymalloy export examples/orders.malloy --format marimo -o report.py
pymalloy export examples/sales.malloynb --format jupyter -o report.ipynb
```

```python
from pymalloy.export import compile, marimo

book = compile("examples/orders.malloy", queries=["orders.by_region"])
text = marimo.render(book, output_path="report.py")
```

The default `precompiled` profile embeds SQL. `server` embeds `ModelSource` and
creates a reusable Python model. `widget` embeds source and registered files for browser
execution. Choose a profile with `profile=` or `--profile`.

Documents preserve Markdown and query order. Models default to run statements,
then named queries, then public views. Explicit `queries` selects names in the
requested order. Use `all=True` or `--all` to select every query.

Data paths follow the exported data root. Relative COPY destinations are anchored
to that root. Marimo output includes dependencies between COPY and following
cells. Jupyter runs in document order.

MalloyWidget exports discover `duckdb.table(...)` files from Malloy syntax. Declare
files read inside SQL explicitly:

```python
book = compile(
    "analysis.malloy", profile="widget", data_root="data",
    files={"orders.csv": "data/orders.csv"},
)
```

`files` registers browser aliases. Native schema discovery uses `data_root`,
so each SQL reader must also resolve through that native connection.

MalloyWidget exports require local files or HTTP(S) URLs and reject native database
state and COPY. Local globs must be replaced with explicit file declarations.
The same inputs, schemas, options, output path, and dependency versions produce
identical notebook bytes.
