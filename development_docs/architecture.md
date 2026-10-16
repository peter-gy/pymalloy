# Architecture and ownership

[Malloy](https://docs.malloydata.dev/) owns language semantics. Python authoring
builds Malloy syntax. Compiler jobs request source text and field schemas.
Runtime adapters fulfil those requests and execute SQL with
[DuckDB](https://duckdb.org/docs/stable/), an embedded SQL database.

## Owners

| Owner                                    | Boundary                                                                               |
| ---------------------------------------- | -------------------------------------------------------------------------------------- |
| `packages/core`                          | Compiler jobs, host driver, shared Model/Query contracts, tooling, documents, metadata |
| `packages/duckdb`                        | DuckDB schema/type conversion, file settings, result materialization                   |
| `packages/node`                          | Native Node sessions, local source readers, connection lifetime                        |
| `packages/browser`                       | WebAssembly workers, virtual files, browser execution                                  |
| `packages/pyodide`                       | Packaged JavaScript entry for Python browser owners and exact wire values              |
| `packages/widget`                        | anywidget revisions, notebook actions, result rendering                                |
| `packages/protocol`                      | Python-facing wire contracts and record generation inputs                              |
| `packages/compiler`                      | Self-contained embedded compiler entry and TypeScript session owner                    |
| `packages/python/rust`                   | Private PyO3 extension, embedded V8 threads, cancellation, heap budgets                |
| `pymalloy._compiler`                     | Native compiler host fulfilment and shared language-tooling lease                      |
| `pymalloy._runtime`                      | Connection owner, native DuckDB execution, operation deadlines                         |
| `pymalloy._browser`                      | Asynchronous Pyodide owners, JavaScript runtime access, exact result decoding          |
| `pymalloy._authoring`                    | Syntax, scoped edits, annotations, Python reconstruction                               |
| `pymalloy._model`                        | Source snapshots, captured inputs, file access, persistence                            |
| `pymalloy._protocol`                     | Generated Python records, exact values, immutable snapshots                            |
| `pymalloy._notebook`, `pymalloy.widget`  | Deferred display, host/view lifetime, Python widget inputs                             |
| `pymalloy.validation`, `pymalloy.export` | Detached evidence, documentation policy, bundles, notebook serialization               |
| `apps`                                   | Composition, documentation site, notebook-host acceptance tests                        |

Core depends on Malloy. DuckDB helpers depend on core. Runtime adapters depend on
both. Python-facing protocol records consume compiler types. Keep filesystem and
database APIs in adapters and format-specific serialization in exporters.

## Compile and execute

`CompiledModel.begin` creates a synchronous job. `step()` returns
`{needs: {urls, schemas}}` or `{result}`. Each requested key receives `{value}` or
`{error}`. Table needs carry `tablePath`, SQL needs carry `sql`, and both carry
connection identity. Hosts construct schema probes and execute on the same engine.
`@malloy-runtime/compiler/adapters` owns `Host`, `drive`, and serialized `Runtime`.

A compiled model retains query descriptors and their output schemas. Required
unbound givens leave the query schema unset. Source schemas remain available.
A query binds givens during SQL preparation and reads current data during execution.
SQL rows stay in the data adapter.

### Source identity and data root

`ModelSource` retains root URL, kind, text, imports keyed by absolute URL, and
captured input owners. Imports resolve exclusively from a closed snapshot.
Python and Node inline source use `model.malloy` under the configured data root.
A Python draft retains its own URL. Browser inline source uses a memory URL.
A virtual translator root distinguishes inline text from a physical import
with the same identifying URL. Diagnostics map back to authored code-point offsets.

Model URLs determine imports. Engine settings determine data resolution.
Owned native connections set UTC and `file_search_path` at creation. DuckDB checks
the process directory before the search path and applies native identifier
precedence. Loading a model keeps the data root unchanged. Browser models copy
virtual-file mappings and activate their files before discovery or execution.

## Resources and cancellation

`pm.connect()` owns an engine and one lock shared by its models. Each model owns
an embedded compiler on a dedicated thread and retains its connection. Queries
retain their model.
Closing a connection waits for work, closes child models, then closes its owned
engine. Closing a model releases its compiler and leaves siblings usable.
Borrowed connections retain caller settings, registrations, and transactions.
The caller owns rollback after a failed statement aborts an explicit transaction.

Operations serialize per Python connection or TypeScript session. A queued
timeout/cancellation rejects that call. Active engine cancellation interrupts
and settles the statement before queued work proceeds. Healthy engines remain
reusable. Python carries one deadline through lock acquisition, compiler requests,
and execution. A completed value or body exception survives a late deadline.

### Browser Python ownership

`pymalloy.browser.connect()` creates an asynchronous connection in Pyodide.
`pymalloy._browser` owns Python operations, task cancellation, deadlines, and
model lifetimes. `packages/pyodide` supplies the packaged JavaScript entry and
delegates compilation and execution to `packages/browser` through its existing
`Session`.
That session owns DuckDB WebAssembly and its worker. Models retain their
connection, immutable source inputs, and virtual-file snapshots. Queries retain
their model. Connection closure aborts pending work, waits for it to settle, and
releases the JavaScript session and worker. Model closure invalidates its queries
while preserving sibling models.

Python/JavaScript calls exchange owned JSON records. Exact givens and result
cells use the shared protocol codec. Browser results retain immutable serialized
data and decode fresh Python containers on access. Widget previews of a browser
model borrow its connection and carry the same stable Malloy result tree as
JavaScript execution. Closing an inspector preserves its borrowed model.

The browser runtime matrix and dependency locks live under `apps/e2e/pyodide`.
Standalone, JupyterLite, and marimo WebAssembly tests install the same release
wheel. Each host uses the dependency lock for its declared runtime.
[Testing](testing.md#pin-the-browser-python-runtime) owns the runtime upgrade
commands.

### Native compiler ownership

[PyO3](https://pyo3.rs/) exposes the private Rust extension as `pymalloy._native`.
The [deno_core](https://docs.rs/deno_core/) Rust library embeds the
[V8](https://v8.dev/) JavaScript engine. Each model's compiler thread owns its
isolate, JavaScript context, retained Malloy model, and active compiler job.
Python sends typed operation data and receives a result, diagnostics, or source
and schema needs. Python fulfils those needs between JavaScript steps. Rust
releases Python's interpreter lock while waiting. Query rows stay in Python's
DuckDB adapter.

The compiler entry exposes `start`, `step`, and `close` inside the isolate.
`packages/protocol` owns request, answer, and result records. Python validates
native output before dispatching it. JavaScript retains Malloy objects, and Rust
owns thread lifetime, job identity, cancellation, and conversion at the native
boundary. Filesystem, network, and database access belong to the Python host.

Active compiler interruption terminates its isolate and closes that model.
Compiler boundary failures and managed heap exhaustion also discard the affected
compiler. Authored diagnostics leave a healthy compiler reusable. SQL timeouts
leave healthy compilers reusable. Browser worker failure closes the session and
settles pending work. Cancellation is tied to the active operation so a late
interrupt cannot terminate the next call. Close settles active work before
releasing its owner.

`compiler_memory_mb` is a managed JavaScript heap budget. Native allocations and
DuckDB memory have separate owners. Fatal V8 failures can terminate Python, and
a native engine stall can delay managed cancellation. Applications requiring
compiler crash containment must scope execution to a separate application
process.

Format, parse, syntax projection, and check lease a shared serialized tooling
compiler with a separate owning thread. It closes after 30 seconds idle. Lease
waiting and startup consume the deadline. Checks resolve schemas and imports
afresh. Diagnostics keep the compiler reusable. Failed compilers are discarded.

Python and Rust compiler owners retain their creator process ID. Operation,
close, finalizer, and tooling entry paths check it before acquiring inherited
locks. Child cleanup abandons inherited native handles. Post-initialization
`fork` cannot reuse connections or compiler owners. Child compilation uses the
`spawn` multiprocessing start method. Same-owner signal-handler reentry must fail
before acquiring an operation lock.

### Widget revisions and views

[anywidget](https://anywidget.dev/) bridges Python and notebook browsers.
Definitions and inputs carry separate revisions. The browser waits for
`input.definitionRevision` to match the definition, cancels superseded work, and
coalesces pending input to the latest revision. Every publication is guarded by
the current generation. Python and renderer guards reject stale results.
Capture materialization and given encoding must succeed before revisions advance.

Initialization owns the browser session and input listeners. Each view owns DOM
and renderer cleanup. Native preview messages carry correlation IDs, input
revisions, and [Arrow IPC](https://arrow.apache.org/docs/format/Columnar.html#serialization-and-interprocess-communication-ipc)
columnar buffers. Browser Python previews use exact protocol records and the
stable Malloy result tree. Closing a widget preserves borrowed models.
Implicit marimo inspectors close on cell rerun through an isolated host lifecycle
seam. Implicit Jupyter inspectors close when their last view unmounts.
Explicit widgets remain caller-owned.

Givens encode integers as exact decimal text recursively through arrays and
records. Result decoding preserves big integers and decimals using schema-tagged
cells. Public state, files, and givens use detached immutable mappings and tuples.
`analysis.to_dict` produces mutable containers while preserving scalar types.

## Authoring and persistence

`Source` and `View` wrap private immutable `Syntax` nodes. Source declarations
append to one trailing `extend` block. View clauses append to the final stage,
including saved-view refinement. `pipe` starts a stage. Annotations bind to named
objects before annotated views enter pipelines.

Named bindings own their expression and directly attached annotation routes.
Lookup and replacement stop at scope boundaries. Parser-projected bindings
retain surrounding source, comments, and shared annotations. Opaque scalar
subtrees keep the whole enclosing scalar opaque because parentheses can change
Malloy temporal-range semantics. `number` retains numeric spelling when it affects
type inference. Python emission reconstructs supported operations and retains
other grammar as trusted literal syntax.

Unchanged file reads and saves preserve exact UTF-8 bytes. Python reconstruction
preserves semantics with canonical supported scalar spelling. Saves publish
complete text atomically, preserve permissions, and compare a loaded file's
observed revision. That comparison cannot lock concurrent writers.
Validated saves check captured imports and their original root directory.

`Connection.validate` captures givens once, compiles once, executes each supplied
counterexample query under one deadline, and closes its model on every path.
It retains structured compiler diagnostics and one row for failed assertions.
Documentation policy reads native annotation metadata, keeping compiler semantics
and presence checks separate.

### Captured input ownership

`_model/inputs.py` owns immutable Arrow IPC snapshots and once-only verified
Parquet materialization. Validation reads bounded batches and compares exact
schema, values, and row counts. Table-reference nodes retain input owners through
composition. Runtime models, queries, snapshots, validation, and execution evidence
retain those owners independently of compiler or connection lifetime.
`ModelSource.inputs` accompanies logical paths. Physical paths are substituted
at the compiler boundary using parsed table-call spans.

Bundles rewrite parsed import and table spans, copy declared files, and record
identities. Explicit files are copied at export time. The producer notebook or
script owns dataframe preparation and its rebuild dependencies.

## Generated contracts and assets

`packages/protocol/src/records.ts` selects the wire contracts.
`scripts/generate-records.ts` produces JSON Schema, frozen Python msgspec records,
and the pinned Malloy keyword lexicon in a temporary directory. It formats them
and validates the full decoder graph before replacing tracked outputs.
`pnpm records:check` compares generated bytes and runs in `pnpm check`.
Change generation inputs and regenerate these artifacts together.

The build stages widget modules, bootstrap/manifest, stylesheet, compiler bundle,
Pyodide runtime, per-artifact dependency notices, and installed agent guidance
into Python assets. `packages/pyodide` emits one closed JavaScript bundle whose
manifest records the bundle and protocol digests and Malloy version. Staging
checks those digests before copying the runtime. Browser packaging verifies its
staged bundle digest.
The native notice generator records the locked Rust dependency licenses and
verified external engine license texts in a manifest checked by Rust's build
script. It stages web-platform JavaScript from the locked extension crates in
`native.runtime.json`. Rust verifies its digest and package versions, then embeds
a source table keyed by `ext:` module specifier. Isolate initialization resolves
all extension sources through that table. A compiler manifest records build inputs
and the bundle digest. Rust
embeds the verified bundle in the native extension. A private Python build
backend verifies SHA-256-pinned V8 archives and bindings, then delegates native
wheel construction to [Maturin](https://www.maturin.rs/).
[Hatch](https://hatch.pypa.io/) builds the
explicit browser wheel. Both builders verify staged assets.
[Packaging](releasing.md) owns distribution checks. Importing `pymalloy` and
constructing syntax leave database and dataframe libraries unloaded.

Native wheels include the extension and browser assets in one distribution.
Their runtime requirements install DuckDB, PyArrow, and timezone data.
The browser wheel keeps the same Python distribution name and version. Its
asynchronous Python adapter and widget use the JavaScript compiler and
DuckDB WebAssembly in Pyodide. Native Python uses the embedded compiler and
DuckDB connection through the synchronous runtime API.

## Notebook exports

Preparation uses one compiler for file discovery and model compilation under one
deadline. A typed notebook plan owns profiles, names, setup, and COPY dependencies.
Format serializers own notebook syntax. Identical source, schemas, options,
output path, and dependencies must yield identical bytes.

Native preparation and generated execution share file-access settings. Allowed
paths include discovered tables, declared SQL readers, and inferred COPY outputs.
Relative COPY paths anchor to the data root. Input shadowing in the current
working directory fails. Remote native inputs load `httpfs` before restrictions
and allow HTTP(S) redirects. Remote bytes remain live.
Widget exports use captured imports and browser virtual files and reject native
database state and COPY. [Export reference](../docs/reference/export.md) owns the
public serialization and replay contracts.
