# Export API

```python
from pymalloy.export import compile, jupyter

book = compile("examples/orders.malloy", all=True)
notebook = jupyter.render(book, output_path="orders.ipynb")
```

`compile(model, *, profile="precompiled", queries=None, all=False, givens=None,
data_root=None, database=None, title=None, timeout=120, files=None)` returns a
`Document`. `model` is a local path. The data root defaults to its parent.
`database` opens read-only. `title` defaults to the filename stem.
`queries` and `all` are mutually exclusive. `queries=None` uses the default
selection and `queries=[]` selects no query cells. The timeout covers the complete
preparation, including imports, compilation, source capture, and SQL classification.

`files` maps widget aliases to local paths for SQL readers. Malloy table syntax
supplies discoverable file references. `Profile` defines `PRECOMPILED`, `SERVER`,
and `WIDGET`.

A `Document` holds title, ordered `Markdown`/`Query` cells, data root, database,
profile, captured source, givens, and files. Query cells contain `name`, `sql`, and
`kind` (`select` or `copy`). Renderers preserve cell order and COPY dependencies.

`marimo.render(document, *, output_path)` returns Python source and requires
`pymalloy[marimo]`. `jupyter.render(document, *, output_path)` returns notebook JSON.
The output path determines portable relative data paths. Rendering returns text
and does not write the output file or execute queries.
