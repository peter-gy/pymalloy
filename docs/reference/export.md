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

## Source bundles

`bundle(source: ModelSource, directory, *, files=None, query=None, givens=None,
format=True, timeout=120) -> SourceBundle` materializes a closed source graph into
a new directory. Its parent must exist. Existing destinations are rejected.
Requires the server compiler for native parsing and formatting.

```python
from pymalloy.export import bundle

parameters = {"minimum": 10}
accepted = candidate.validate(checks, givens=parameters).require_valid()
artifact = bundle(
    accepted.source,
    "orders-export",
    files={"orders.parquet": "data/orders.parquet"},
    query="by_region",
    givens=parameters,
)
```

`SourceBundle.model`, `.data_root`, and `.manifest` are paths. `bundle.json` records
the selected query, parameter bindings, compiler version, source identities and
SHA-256 hashes of emitted source and copied data. Load `.model` with
`data_root=artifact.data_root`, then select the manifest's query and pass its givens.

Every import is rewritten using Malloy's parsed string-literal span. Selective
imports keep their selected names. Source files may originate at different URLs,
and an inline root may share its identity with an imported physical file.
Missing imports and malformed source fail before publishing the destination.
`format=False` retains authored formatting around the rewritten references.

`files` maps table references to local input files. String keys match the exact
Malloy table path. Use a `Path` key for a reference constructed with `pm.table(Path)`.
Bound `duckdb.table` calls reference the copied data. Relative string keys also
provide aliases for SQL readers through `file_search_path`. SQL text is retained.
Database state and undeclared reader dependencies remain the caller's responsibility.

Materialization checks source syntax and closure. It does not execute a query or
establish that the selected parameters and data produce the intended result.
Revalidate and replay from the exported directory. See the executable artifact
recipe distributed with `pymalloy.agent.agent_skill()` at
`references/artifacts.md`.
