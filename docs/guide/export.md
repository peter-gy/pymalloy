# Export notebooks

Prepare [Malloy](https://docs.malloydata.dev/) query cells, then render them as a
[marimo](https://docs.marimo.io/) reactive Python notebook or
[Jupyter](https://docs.jupyter.org/) notebook document.
Install `pymalloy[headless]` for preparation. Run from the repository root to use
its `examples/orders.malloy` fixture:

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from pymalloy.export import jupyter, marimo, prepare

book = prepare("examples/orders.malloy", queries=["orders.by_region"])
with TemporaryDirectory() as directory:
    output = Path(directory)
    (output / "report.py").write_text(marimo.render(book, output_path=output / "report.py"))
    (output / "report.ipynb").write_text(jupyter.render(book, output_path=output / "report.ipynb"))
    print([query.name for query in book.queries])
```

Expected output is `['orders.by_region']`. Renderers return text.
`output_path` determines relative data references. The example writes temporary
notebooks. For sharing, choose a persistent output directory and keep the data
at the referenced relative paths. Use [source bundles](bundles.md) to copy inputs.

The equivalent command for a persistent notebook is:

```sh
pymalloy export examples/orders.malloy --format marimo --query orders.by_region -o /tmp/report.py
```

## Choose execution

| Profile                 | Generated notebook behavior                                                                       |
| ----------------------- | ------------------------------------------------------------------------------------------------- |
| `precompiled` (default) | Executes embedded SQL with native [DuckDB](https://duckdb.org/docs/stable/), an embedded database |
| `headless`              | Compiles captured `ModelSource` and runs queries with `pymalloy[headless]`                        |
| `widget`                | Sends captured source and virtual files to browser widgets with `pymalloy`                        |

Pass `profile=` or `--profile`. Preparation requires the headless compiler for
every profile. Install the notebook host and dependencies declared in the
artifact to run it. Widget execution uses browser assets. Run Jupyter kernels
from the exported notebook's directory so relative references resolve correctly.

Documents preserve Markdown, Malloy, and SQL cell order. Plain models select
runs first, then named queries, then public views. `queries` selects names in the
requested order. `all=True` or `--all` selects every query.

## Declare reader inputs

Malloy table files are discovered. Declare local files hidden inside SQL readers:

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from pymalloy.export import prepare

with TemporaryDirectory() as directory:
    root = Path(directory)
    (root / "orders.csv").write_text("amount\n20\n22\n")
    model = root / "orders.malloy"
    model.write_text("run: duckdb.sql(\"SELECT * FROM read_csv('orders.csv')\") -> { select: amount }")
    book = prepare(model, data_root=root, files={"orders.csv": root / "orders.csv"})
    print(len(book.queries))
```

Expected output is `1`. Native profiles restrict file access to discovered table
files, declared reader files, and inferred COPY destinations during preparation
and generated execution. Native aliases must resolve to their declared paths
through `data_root`. A conflicting current-directory input raises an error.
Relative COPY destinations are anchored to the exported data root.
Marimo retains dependencies between COPY and subsequent cells. Jupyter executes
in document order.

HTTP(S) table URLs are discovered. Declare URLs hidden inside SQL with
`remote_files=[url]` or repeat `--remote-file URL`. Remote native notebooks install
and load DuckDB's `httpfs` extension and permit HTTP(S) access including redirects.
Preparation and execution require network access. Remote responses stay live.
Use local copies when inputs must be fixed.

Widget exports require local files or HTTP(S) URLs. They reject native database
state, COPY, and local globs. Declare explicit files for those globs before export.
Remote widget inputs need cross-origin resource sharing permission from the server.
The same inputs, schemas, options, output path, and dependency versions produce
identical notebook bytes. See [export reference](../reference/export.md) and
[CLI flags](../reference/cli.md#export).
