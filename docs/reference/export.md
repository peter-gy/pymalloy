# Export API

```python
from pymalloy.export import prepare, jupyter

book = prepare("examples/orders.malloy", all=True)
notebook = jupyter.render(book, output_path="orders.ipynb")
```

`prepare(model, *, profile="precompiled", queries=None, all=False, givens=None,
data_root=None, database=None, connection_name="duckdb", title=None, timeout=120,
files=None, remote_files=(), extensions=())` returns a
`Document`. `model` is a local path. The data root defaults to its parent.
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
defines `PRECOMPILED`, `SERVER`, and `WIDGET`.

`remote_files` declares absolute HTTP(S) URLs used inside SQL readers. Direct
Malloy table URLs are discovered automatically. Remote-enabled native profiles
install and load `httpfs` and allow HTTP(S) access, including redirects. These
URLs identify live inputs, not frozen response bytes. Preparation and execution
need network access.

`extensions` names DuckDB extensions to install and load before restricting file
access, both during preparation and in generated native notebooks. The widget
profile rejects this option; its execution uses DuckDB WebAssembly's extension
support.

A `Document` holds title, ordered `Markdown`/`QueryCell` cells, data root, database,
profile, captured source, givens, local files, remote URLs, extensions, and connection name. Query cells contain `name`, `sql`, and
`kind` (`select` or `copy`). These `pymalloy.export.QueryCell` records describe notebook cells. Renderers preserve cell order and COPY dependencies.

`marimo.render(document, *, output_path)` returns Python source. Running that
notebook requires `pymalloy[marimo]`. `jupyter.render(document, *, output_path)` returns notebook JSON.
The output path determines portable relative data paths. Rendering returns text
and does not write the output file or execute queries.

## Source bundles

`bundle(source: Validation | ModelSource, directory, *, files=None, query=None,
givens=None, connection_name=None, format=True, timeout=120) -> SourceBundle`

Write plain `.malloy` sources, captured imports, copied inputs, `model.py`,
`replay.py`, and `bundle.json` into a new directory. The parent must exist.
Existing destinations and notebook document sources are rejected. Native parsing
and optional formatting require the server compiler. Publication occurs after
source and file preparation succeeds.

See [bundle models and inputs](../guide/bundles.md) for a complete validation and
replay workflow.

### Source and bindings

- `Validation` must be successful. It supplies captured imports, managed inputs,
  and the exact givens used during validation. A supplied `query` must name a
  query in that model. Different explicit givens or a conflicting connection
  name are rejected.
- `ModelSource` supplies source and imports only. The caller supplies any data
  bindings and givens. `connection_name` defaults to `"duckdb"`. Bundling checks
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
Parquet hashes and cannot be replaced through `files`. Database state and
undeclared reader dependencies remain requirements of the exported model.

### Return value and manifest

`SourceBundle.model`, `.data_root`, and `.manifest` are filesystem paths.
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

Capture IDs distinguish separate `pm.data` calls. They are not content hashes.
The manifest has no whole-bundle identity, output dataset, expected result hash,
or environment lock. Assertion definitions, diagnostics, and human review remain
outside the manifest.

### Replay

`replay.py` reads the manifest, loads the emitted Malloy with its data root, and
runs the selected query using the recorded givens and connection name. It rejects
a copied input alias shadowed by a different file in the current directory. It exposes `result` when loaded
with `runpy.run_path` and closes its model before returning. It uses the installed
runtime and does not check recorded hashes, enforce versions, or rerun assertions.

`model.py` reconstructs editable grammar against the bundled files. It does not
recover the Python code that prepared an input dataframe. Retain that notebook or
producer script separately, and verify results after relocation or environment changes.
