# Export notebooks

Notebook export prepares ordered cells for marimo or Jupyter. To copy a semantic
model and its inputs into a directory, use [source bundles](bundles.md).

Prepare a Malloy file or document, then choose a notebook format:

```sh
pip install 'pymalloy[headless]'
pymalloy export examples/orders.malloy --format marimo -o report.py
pymalloy export examples/sales.malloynb --format jupyter -o report.ipynb
```

```python
from pymalloy.export import prepare, marimo

book = prepare("examples/orders.malloy", queries=["orders.by_region"])
text = marimo.render(book, output_path="report.py")
```

Choose an execution profile with `profile=` or `--profile`:

| Profile                 | Execution in the generated notebook                                       |
| ----------------------- | ------------------------------------------------------------------------- |
| `precompiled` (default) | Embedded SQL executed by native DuckDB, without PyMalloy                  |
| `headless`              | Captured `ModelSource` compiled and executed with `pymalloy[headless]`    |
| `widget`                | Captured source and virtual files sent to browser widgets with `pymalloy` |

Preparing any profile requires the headless compiler. Running an exported widget
notebook requires no Deno. Renderers retain relative references to local data
files, which must accompany the notebook. They do not copy a source bundle.

Documents preserve Markdown and query order. Models default to run statements,
then named queries, then public views. Explicit `queries` selects names in the
requested order. Use `all=True` or `--all` to select every query.

Data paths follow the exported data root. A conflicting file in the current
directory raises an error so it cannot silently replace the exported input.
Relative COPY destinations are anchored
to that root. Marimo output includes dependencies between COPY and following
cells. Jupyter runs in document order.

Exports discover table files from Malloy syntax. Declare files read inside SQL
explicitly for every profile:

```python
book = prepare(
    "analysis.malloy", profile="widget", data_root="data",
    files={"orders.csv": "data/orders.csv"},
)
```

`files` supplies source file names and local paths. Native profiles restrict
DuckDB file access to discovered table files, declared reader files, and inferred
COPY destinations during preparation and execution. File names must resolve to
their declared paths through `data_root`. Widget profiles register the names as
browser aliases, while native schema discovery must still resolve the inputs.

HTTP(S) table sources are discovered automatically. Declare URLs inside native
SQL readers with `remote_files=["https://example.org/orders.parquet"]` or repeat
`--remote-file` on the CLI. Native notebooks with remote inputs install and load
DuckDB's `httpfs` extension. They permit HTTP(S) access, including redirects, and
require network access during preparation and execution. Remote response bytes
are not captured. Use local files when the exported inputs must be fixed.

MalloyWidget exports require local files or HTTP(S) URLs and reject native database
state and COPY. Local globs must be replaced with explicit file declarations.
The same inputs, schemas, options, output path, and dependency versions produce
identical notebook bytes.
