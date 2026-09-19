# Architecture and ownership

Malloy owns language semantics. Python authoring produces Malloy syntax. Compiler
jobs request source text and field schemas. Runtime adapters fulfil those requests
and execute SQL with DuckDB. Exporters publish source files or notebook documents.

The public [concepts guide](../docs/guide/concepts.md) defines the user-facing
values. This page assigns their implementation owners.

## Follow a query

1. A host calls `CompiledModel.begin` with source identity, optional inline text,
   a document kind, and a connection name and dialect.
2. `Job.step()` drives `MalloyTranslator.translate()`. It returns a result or
   import/schema needs. Table schema needs carry native table paths, and SQL schema
   needs carry SQL text. Adapters construct their own probes. The next step
   receives an answer for every requested key.
3. A retained model exposes typed query descriptors. A `Query` selects a name or
   Malloy extension and binds givens when producing SQL.
4. The host executes SQL on the same connection used for schema discovery and
   materializes a `Result`.

Node and browser hosts await I/O between synchronous steps. Python fulfils the
same needs synchronously. Compiler jobs contain no connection or filesystem APIs.

## Owners

| Owner                                        | Responsibility                                                                                        |
| -------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `packages/core` (`@malloy-runtime/compiler`) | Synchronous compiler jobs, shared Model/Query contracts, documents, diagnostics, metadata and tooling |
| `packages/duckdb`                            | DuckDB type conversion, search-path statements, Arrow materialization and stable result conversion    |
| `packages/node`                              | Native connection ownership, local source readers and session execution                               |
| `packages/browser`                           | WebAssembly worker ownership, virtual files, imports and execution                                    |
| `packages/widget`                            | anywidget revision synchronization and Malloy result rendering                                        |
| `packages/protocol`                          | Shared Python wire contracts, exact givens, and widget state                                          |
| `packages/headless`                          | Deno compiler service and framed process entry point                                                  |
| `pymalloy._headless`                         | Deno process, Python DuckDB engine, model ownership and deadlines                                     |
| `pymalloy._authoring`                        | Immutable syntax, scoped drafts, annotations, and Python reconstruction                               |
| `pymalloy._model`                            | Source snapshots, captured data, persistence, selection, and shared failure contracts                 |
| `pymalloy._protocol`                         | Generated compiler/widget records, exact givens, result decoding, and immutable wire snapshots        |
| `pymalloy.validation`                        | Detached reports and documentation-presence policy                                                    |
| `pymalloy._notebook`                         | Deferred notebook projections, rich display hooks and cell lifetime ownership                         |
| `pymalloy.widget`                            | Python inputs and detached widget snapshots                                                           |
| `pymalloy.export`                            | Source bundles, notebook plans, COPY destination anchoring, and format serialization                  |
| `apps`                                       | Documentation and notebook-host acceptance tests                                                      |

Dependency direction follows these owners. Core depends on Malloy. DuckDB helpers
depend on core. Node and browser adapters depend on both. Python-facing protocol
records depend on compiler types, and the widget and Deno service consume them.
Core and DuckDB helpers never depend on those protocol records or Python adapters.

### Python package layout

The package root contains the public modules: `authoring`, `expressions`,
`analysis`, `result`, `execution`, `validation`, `browser`, `widget`, `agent`, and
`cli`. The root `__init__.py` exposes the main Python API and loads optional
runtimes on demand.

Private packages own related implementation files:

| Package      | Files and role                                                                                                                                                                                                                             |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `_authoring` | `draft.py` coordinates edits, `syntax.py` owns fragments, `operations.py` renders scalar operations, and `python.py` reconstructs Python. Annotations, identifiers, generated lexer keywords, and table-reference syntax live beside them. |
| `_model`     | `source.py` owns source identity and snapshots, `inputs.py` captures data, `persistence.py` publishes source, and `selection.py` validates query selection. Shared errors and the default connection name belong here.                     |
| `_protocol`  | `records.py` contains generated frozen, strict msgspec types. `givens.py`, `codec.py`, and `snapshot.py` encode values, decode results, and freeze boundary data.                                                                          |
| `_notebook`  | `subject.py` projects authored metadata and deferred native operations. Display hooks and `lifetime.py` own implicit views.                                                                                                                |
| `_headless`  | Compiler processes, tooling leases, native engine execution, deadlines, and retained runtime models.                                                                                                                                       |
| `export`     | Public notebook/bundle APIs and their private document, planning, file-access, and serialization modules.                                                                                                                                  |

`_protocol` is independent of runtime and authoring code. `_model` depends on
protocol types and imports Arrow when capturing data. Authoring consumes both
packages. Parsing, formatting, checking, and compilation load the compiler/headless
code on demand. Widget and export adapters reuse those values. Keep package initializers small
and import private definitions from their owning modules.

The base Python package includes syntax construction, source records, anywidget,
and agent guidance. Optional components are imported at their use sites. The
`headless` extra supplies Deno, native DuckDB, PyArrow and timezone data.
`pm.data` loads PyArrow when called. Polars and notebook hosts are installed
directly when needed. Separate compiler and widget bundles let browser execution
remain independent of Deno.
Deno comes from its Python distribution, giving headless installs a packaged
JavaScript runtime. Its permission sandbox and V8 heap limit bound compiler
access and memory independently of DuckDB. Native DuckDB supplies Arrow results.
Timezone-aware Arrow values retain their timezone through PyArrow conversion.

## Source and data

`ModelSource` is a closed source snapshot: root URL, document kind, root text,
and imported text keyed by URL. Hosts infer kind from file extensions once unless
the caller supplies it. Compiler jobs consume the explicit kind. Default inline
filenames are `model.malloy`. Native hosts resolve that name against the current directory,
while browser-only text uses the shared memory URL. These bases determine relative
import resolution. A virtual translator root keeps inline text distinct from an
imported physical source with the same identifying URL. Diagnostics map back to
authored source identity and code-point coordinates.

A model's URL determines import resolution. DuckDB connection settings determine
data resolution. Owned native sessions set UTC and `file_search_path` at creation.
DuckDB checks the current process directory before `file_search_path`. Catalog
identifiers and CTEs retain DuckDB's native precedence. Loading a model never
changes the data root. Borrowed connections use caller settings and reject
connection options that would mutate them.

Browser models snapshot virtual-file mappings. The session activates a model's
files before discovery or execution. HTTP sources require CORS. Captured source
imports resolve exclusively through the snapshot.

## Resources and cancellation

| Resource                               | Owner and teardown                                                      |
| -------------------------------------- | ----------------------------------------------------------------------- |
| Owned native connection                | Python model or TypeScript session, closed after submitted work settles |
| Borrowed native connection             | Caller, including settings and transactions                             |
| Browser worker and database            | Session, terminated on close, worker failure, or session-lifetime abort |
| Import requests                        | Operation signal, also cancelled when the session closes                |
| Retained Deno process and compiler job | Python model, released on close or collection                           |
| Compiler-only Deno process             | Serialized tooling lease, released after 30 seconds idle or at exit     |
| MalloyWidget session                   | anywidget initialization, released by initialization cleanup            |
| MalloyWidget DOM and renderer          | Rendered view, listeners and visualization disposed on cleanup          |
| Precompiled notebook connection        | Query cell, closed after materialization or COPY                        |
| Headless notebook model                | Generated setup shared by query cells                                   |

Operations serialize per Python model or TypeScript session. Queued cancellation
rejects that call. Active engine cancellation interrupts the statement and waits
for acknowledgement before queued work starts. Healthy engines remain reusable.
An interrupted caller-owned transaction may require rollback by its owner.
TypeScript accepts `AbortSignal`, including `AbortSignal.timeout(ms)`. Python
measures seconds across lock acquisition, compilation and execution. Compiler
requests receive the remaining budget. A compiler request timeout kills Deno
because its request framing can no longer be trusted, making that model terminal.
Worker death and compiler crashes also close the affected runtime.
`compiler_memory_mb` limits the compiler V8 heap independently of DuckDB memory.
`pm.run` closes resources before returning. Retained Python models use finalizer
cleanup, expose `close()` for early release, and support optional context management. Queries keep their model alive.

## Notebook display

`NotebookDisplay` supplies marimo's `_display_` and Jupyter's `_repr_mimebundle_`
hooks. It creates an inspection-first MalloyWidget for each display. Subject
projection reads authored structure and retained metadata. It neither compiles
nor materializes captured inputs. Check and Run requests trigger that work.
Isolated expressions and clauses keep their unresolved context visible.

Browser subjects use the existing browser session adapter. Native subjects
borrow a model and send bounded preview results as Arrow IPC over standard
anywidget custom messages. Materialized results use the same transport for a
20-row slice. The widget reuses DuckDB Arrow conversion and Malloy stable-result
rendering. Native previews carry column types and values, while browser query
results also retain Malloy rendering annotations.

Implicit views close when their last frontend view unmounts. In marimo,
`_notebook/lifetime.py` also registers with the private cell lifecycle registry:
marimo closes a comm on cell rerun, while ipywidgets retains its Python widget
until `close()`. This isolated host seam releases captured inputs and borrowed
model references on rerun and deletion. Explicit MalloyWidget instances keep
caller ownership. Closing a view never closes a borrowed native model.

## Records and rendering

TypeScript records use camel case. `packages/protocol` owns the wire contracts and
their generated JSON Schema. `scripts/generate-records.ts` emits Python msgspec
records with Python field names and wire aliases. Authored
dictionary keys retain their spelling. Incoming messages are validated at the
boundary. [Protocols and lifecycle](protocol.md) owns transport shapes, exact
values, and widget revision rules.

Node and browser results contain native rows and a Malloy stable result tree.
The widget transports that tree to Python as recursively immutable mappings and
tuples. `pymalloy.analysis.to_dict(state)` explicitly materializes mutable copies. Native Python
results retain DuckDB-produced Arrow tables. Row conversion materializes Python
objects on demand, while `.arrow()` returns the retained table. SQL rows never pass through
the Deno compiler process.

The widget uses `@anywidget/react` and stable external-store subscriptions.
React owns each view's controls, tabs, schema glyphs and diagnostic presentation. Each
view has a shadow root, with StyleX tokens and compiled component rules isolated
from notebook form styles. The host stylesheet contains only the shadow-host
layout reset. Malloy's renderer owns result DOM and authored rendering tags inside
one effect-managed adapter, including its style and accessibility observers.
Initialization owns the shared session and input listeners.

`anywidget-bundle` owns the bootstrap, manifest and module transport. Its Python
`BundledWidget` base serves packaged JavaScript chunks over the existing comm.
The browser compiler, native Arrow adapter and result visualization load on
request. Notebook inspection starts with the React app and its stylesheet.
StyleX exposes the renderer's CSS fallback theme variables so authored Malloy
theme annotations keep their precedence.

Malloy adaptation lives in `core/src/upstream.ts`, including translator creation,
parser access, experimental formatting and internal metadata conversions. Parser
listeners use Malloy's generated context types so grammar drift fails typechecking.

## Repeated work and result conversion

A compiled model owns one typed query registry. Embedded queries retain their
validated preparation and SQL fragments, so first execution uses the schemas
already discovered during compilation. Each call binds its own givens
and executes against current data. Named queries, runs, and retained source views
keep one native `PreparedResult` for calls without supplied values, following
Malloy's `QueryMaterializer` default-compilation policy. Nonempty givens and ad hoc
source compile per request. Query rows are always fetched from the engine.
SQL-only calls leave rendering metadata unevaluated, and each result publication
gets fresh stable metadata.

Inspection traverses Malloy's given objects once and reuses source schemas from
its stable `ModelInfo`. Queries needing runtime givens still expose source-only
metadata through Malloy's source converter. Native table discovery can skip the
coordinate-repair walk when Malloy reports no table references.

Browser models keep a bounded output-schema cache keyed by SQL and Arrow schema.
Dictionary schemas and large keys bypass it. Cache entries contain column
descriptions, not rows. Model file snapshots copy input buffers before queued work.

Browser Arrow conversion plans decoders per field and reads column vectors.
Python retains the engine's Arrow buffers and schema directly. Public row reads
return detached values. Non-finite values copy only changed result
branches before browser rendering. Widget result messages disable anywidget echo
because the browser already owns the publication.

Native notebook previews send a memory view of the Arrow IPC buffer. Python
readback validates one detached wire tree shared by its decoder and state
resynchronization. Publishing the public snapshot freezes its own containers,
so mutations to incoming frames cannot change retained snapshots.

Idle Deno processes exit through stdin EOF to let Deno persist its code cache.
Active failures terminate the child. Both shutdown paths have bounded waits.

See [authoring internals](authoring.md) for syntax and input materialization costs,
and [benchmarks](testing.md#measure-authoring-and-dataframe-costs) for reproducible
measurements.

## Notebook exports

Compiler documents preserve Markdown, Malloy and SQL order, including embedded
query splicing and authored diagnostics. `Document` carries public givens, files,
source, profile and ordered cells.

A shared typed notebook plan owns execution profiles, setup, query naming and
COPY dependencies. Marimo and Jupyter serializers supply format-specific syntax.
Export preparation carries one deadline through every phase.

Precompiled notebooks set `file_search_path` and the `data_root` variable on each
connection. The exporter anchors relative COPY destinations using that variable. Export
preparation and generated native execution reject a relative input shadowed by
a different file in the current directory. Native preparation and generated
execution set DuckDB's `allowed_paths` to discovered table files, explicit reader
files and inferred COPY destinations, with external access otherwise disabled.
Remote inputs enable HTTP(S) directory prefixes so redirects remain usable.
Native profiles install and load `httpfs` before applying those restrictions.
`Document.remote_files` records discovered table URLs and explicitly declared
SQL reader URLs. Remote bytes remain live dependencies.
Headless notebooks hydrate `ModelSource` and use `model.query(name).run()`. MalloyWidget
notebooks create `MalloyWidget` instances from source and registered files. The exporter
uses public model, parse, and connection methods.

MalloyWidget file discovery uses Malloy table-path metadata. Readers inside SQL require
explicit `files`. MalloyWidget exports reject COPY and native database state.
Marimo serialization writes the public Python notebook format and derives cell
dependencies with Python's symbol table. It adds dependencies after COPY. Jupyter executes cells
in order. Identical inputs, schemas, options, output paths and dependencies must
produce identical notebook bytes.

## Source bundles

The [authoring layer](authoring.md#source-artifacts-and-failures) retains captured
input owners through drafts, validations, models, and execution evidence. Bundle
export consumes those owners alongside a closed source graph. It rewrites native
import and table spans, copies declared inputs, and publishes a new directory.

Source bundles and notebook documents have separate contracts. Bundles publish
files and replay metadata. Notebook export prepares ordered cells and a runtime
profile. Neither supplies a dataset-specific intent record, output comparison,
or the Python producer's dependency graph. Those belong to the consuming project.
The [export reference](../docs/reference/export.md) owns the file and replay contract.
