# Export API

`pymalloy.export` prepares [Malloy](https://docs.malloydata.dev/documentation/)
source for notebooks and publishes source bundles. Malloy compiles the queries.
[DuckDB](https://duckdb.org/docs/stable/) supplies native schemas and execution.
Preparation requires `pymalloy[headless]`.

```python
from pymalloy.export import prepare, jupyter

book = prepare("examples/orders.malloy", all=True)
notebook = jupyter.render(book, output_path="orders.ipynb")
assert len(book.queries) == 3
print([query.name for query in book.queries])
```

`prepare(path, *, profile="precompiled", queries=None, all=False, givens=None,
data_root=None, database=None, connection_name="duckdb", title=None, timeout=120,
files=None, remote_files=(), extensions=())` returns a
`Document`. `path` is a local source path. The data root defaults to its parent.
`database` opens read-only. `title` defaults to the title-cased filename stem
with underscores replaced by spaces.
`queries` and `all` are mutually exclusive. `queries=None` uses the default
selection and `queries=[]` selects no query cells. The timeout covers the complete
preparation, including imports, compilation, source capture, and SQL classification.

`files` maps source file names to local paths for SQL readers. Malloy table syntax
supplies discoverable file references. Native profiles restrict external file
access to discovered and declared paths, plus inferred COPY destinations. This
restriction applies during preparation and generated execution. Native file aliases must resolve to their
declared location relative to `data_root`, or use an absolute path. `Profile`
defines `PRECOMPILED`, `HEADLESS`, and `WIDGET`.

`remote_files` declares absolute HTTP(S) URLs used inside SQL readers. Direct
Malloy table URLs are discovered automatically. Remote-enabled native profiles
install and load `httpfs` and allow HTTP(S) access, including redirects. These
URLs identify live inputs, not frozen response bytes. Preparation and execution
need network access.

`extensions` names DuckDB extensions to install and load before restricting file
access, both during preparation and in generated native notebooks. The widget
profile rejects this option. Its execution uses
[DuckDB WebAssembly](https://duckdb.org/docs/stable/clients/wasm/overview),
a browser SQL engine.

## Document and cells

`pymalloy.export.Document(title, cells, data_root, database=None, source=None,
givens={}, profile=Profile.PRECOMPILED, files={}, connection_name="duckdb",
remote_files=(), extensions=())` is frozen. Mappings are copied into read-only
snapshots. `cells` is a tuple and `data_root` is a `Path`. `.queries` returns the
tuple of notebook query cells in document order.

A `Document` holds title, ordered `MarkdownCell`/`NotebookQuery` cells, data root, database,
profile, captured source, givens, local files, remote URLs, extensions, and connection name. Query cells contain `name`, `sql`, and
`kind` (`select` or `copy`). `pymalloy.export.NotebookQuery(name: str, sql: str, kind: Literal["select", "copy"])`
is frozen and raises `ValueError` for any other kind. `pymalloy.analysis.MarkdownCell(*,
text: str)` is re-exported as `pymalloy.export.MarkdownCell` for prose cells. Renderers preserve cell order and COPY dependencies.

`Profile` is `pymalloy.export.Profile`, a string enum with `PRECOMPILED`,
`HEADLESS`, and `WIDGET` members. Native profiles require file aliases resolving
through `data_root`. A precompiled document has `source=None`. Headless and widget
documents require a captured `ModelSource`. Invalid profiles, inconsistent source,
file bindings, URLs, or extension settings raise `ValueError`.

## Renderers

[marimo](https://docs.marimo.io/) is a reactive Python notebook editor.
[Jupyter](https://docs.jupyter.org/) hosts ordered notebook kernel cells.

`marimo.render(document, *, output_path)` returns Python source. Running that
notebook requires `marimo` plus the dependencies declared by its execution profile. `jupyter.render(document, *, output_path)` returns notebook JSON.
The output path determines portable relative data paths. Rendering returns text
and does not write the output file or execute queries.

## Source bundles

`bundle(source: Validation | ModelSource, directory, *, files=None, query=None,
givens=None, connection_name=None, format=True, timeout=120) -> SourceBundle`

Write plain `.malloy` sources, captured imports, copied inputs, `model.py`,
`replay.py`, and `bundle.json` into a new directory. The parent must exist.
Existing destinations and notebook document sources are rejected. Native parsing
and optional formatting require the headless compiler. Publication occurs after
source and file preparation succeeds.

See [bundle models and inputs](../guide/bundles.md) for a complete validation and
replay workflow.

### Source and bindings

- `Validation` must be successful. It supplies captured imports, managed inputs,
  and the exact givens used during validation. A supplied `query` must name a
  query in that model. Different explicit givens or a conflicting connection
  name are rejected.
- `ModelSource` supplies source, imports, and captured input owners in `inputs`.
  The caller supplies external file bindings and givens. `connection_name` defaults to `"duckdb"`. Bundling checks
  syntax and import closure, without semantic compilation or query execution.
- `query=None` leaves replay to the model's default selection. A `ModelSource`
  query name is recorded without checking that it exists.
- `format=False` keeps authored formatting around rewritten references.
- `files` maps `str | Path` table references to local regular files. String keys
  match exact Malloy table paths. Use a `Path` key for `pm.table(Path(...))`.

Malloy's parsed spans identify import literals and bound table calls to rewrite.
Selective imports retain their selected names. Source files can originate
at different URLs. SQL text remains unchanged. Relative string file bindings also
provide aliases for SQL readers through `file_search_path`.

Explicit files are copied at export time, independently of the data seen during
validation. Managed dataframe inputs are checked against their materialized
[Parquet](https://parquet.apache.org/docs/) columnar-file hashes and cannot be replaced through `files`. Database state and
undeclared reader dependencies remain requirements of the exported model.

### Return value and manifest

`pymalloy.export.SourceBundle(model: Path, data_root: Path, manifest: Path)` is a
frozen result record. `SourceBundle.model`, `.data_root`, and `.manifest` are filesystem paths.
Manifest paths are relative to the bundle directory. The current
`bundle.json` uses `format_version: 3`:

| Field                | Contents                                                                                       |
| -------------------- | ---------------------------------------------------------------------------------------------- |
| `compiler_version`   | Version used to parse and format the export                                                    |
| `model`, `data_root` | Relative root model and data directory paths                                                   |
| `connection_name`    | Malloy connection name used by replay                                                          |
| `query`, `givens`    | Selected query or `null`, and exact JSON-compatible parameter bindings                         |
| `sources`            | Source URLs, emitted paths, original-text SHA-256 and emitted-file SHA-256                     |
| `files`              | Bound references, data-root-relative aliases, copied paths, and copied-file SHA-256            |
| `inputs`             | Managed input IDs, names, row counts, schemas, Arrow snapshot hashes, and Parquet paths/hashes |
| `validation`         | `null` for `ModelSource`, otherwise success and each check's name, status, and SQL             |

Capture IDs distinguish separate `pm.data` origins. File hashes identify copied
contents. The producing project retains assertion definitions, diagnostics, human
review, environment specifications, and expected-output comparisons.

### Replay

`replay.py` reads the manifest, loads the emitted Malloy with its data root, and
runs the selected query using the recorded givens and connection name. It rejects
a copied input alias shadowed by a different file in the current directory. It exposes `result` when loaded
with `runpy.run_path` and closes its connection before returning. It uses the installed
runtime. The caller owns hash verification, version enforcement, and rerunning
assertions when those are replay requirements.

`model.py` reconstructs editable grammar against bundled files. Retain the
producer notebook or script to rebuild dataframe inputs, and verify results after
relocation or environment changes.
