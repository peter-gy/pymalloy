# Architecture and ownership

Malloy owns parsing, name resolution, types, and SQL generation. PyMalloy supplies
data access, executes DuckDB SQL, and displays or exports results.

## Follow a query

1. A session supplies source text, its identifying URL, an import reader, and a
   `describe(sql)` callback to `CompiledModel.load`.
2. Malloy requests imports and schemas. Core converts schema requests into SQL
   for the runtime to describe.
3. The compiled model exposes query selectors and metadata. Selecting a query
   binds its givens, the inputs declared in Malloy source, and produces SQL.
4. The runtime executes SQL through the connection and data access rules used
   for schema discovery, then materializes the result.

A **compiled model** snapshots resolved source, imports, and schemas. Re-running
it reads current data. Reload it after source or schema changes. A **session**
owns compilation and execution resources. A **query selector** identifies a run
statement, named query, exported source view, or SQL document cell.

## Put changes with their owner

| Owner                                       | Responsibility                                                                                  |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `packages/core`                             | Compiler integration, query selection, diagnostics, inspection, and ordered document cells      |
| `packages/node`                             | Native Node DuckDB connections, local imports, data path binding, and queued execution          |
| `packages/browser`                          | DuckDB WebAssembly workers, virtual files, browser imports, and Arrow result conversion         |
| `packages/widget`                           | anywidget model initialization, input/result transport, query controls, and result rendering    |
| `packages/python/src/pymalloy/widget.py`    | Python widget inputs, trait validation, detached state snapshots, and close behavior            |
| `packages/python/src/pymalloy/browser.py`   | Browser asset configuration records for Python widget construction                              |
| `packages/python/src/pymalloy/server`       | Python DuckDB connections, Deno process, operation deadlines, model handles, and native results |
| `packages/python/src/pymalloy/_document.py` | Immutable document records shared by native compilation and exporters                           |
| `packages/python/src/pymalloy/exports`      | Export options and format-specific notebook serialization                                       |
| `apps/python-bridge`                        | Adapter between the Python process protocol and the shared compiler                             |
| `apps/e2e`                                  | Notebook-host acceptance tests and their local servers                                          |
| `apps/docs`                                 | Public site configuration and theme                                                             |

The compiler receives a URL reader and `describe(sql)` callback. Runtime adapters
own filesystem access, credentials, workers, and database connections. The bridge
depends on core and receives schemas from Python. Keep Malloy internal metadata
and experimental formatting access in `core/src/upstream.ts`.

## Keep public boundaries deliberate

Python namespaces expose:

- `pymalloy`: widget and `ModelSource`.
- `pymalloy.browser`: browser asset configuration.
- `pymalloy.server`: native execution.
- `pymalloy.analysis`: language report records.
- `pymalloy.exports`: document records and compilation, with format renderers in
  `.marimo` and `.jupyter`.

The base package must import with its anywidget and traitlets dependencies.
`server` owns the Deno, DuckDB, Polars, Arrow, and SQLGlot dependencies. Its private
`NativeRuntime` owns the connection, bridge, and operation budget. `DataAccess`
binds and describes SQL against that connection. The public `Session` extends
`NativeRuntime` with retained models and query execution. Export compilation uses
the same services through `server/_documents.py`.

Document records import independently of native dependencies. Renderers use
those records and the standard library. `compile_document()` loads the compiler
on demand.

`ModelSource` holds an immutable root URL, original text, and import mapping.
Root text is separate so an inline root and imported file can share a URL with
different text. Widgets and native hydration use this snapshot, discovering
schemas in the receiving session. Widget definitions synchronize source
separately from data files. Browser `url` and `imports` options preserve captured
source identities.

JavaScript export maps expose each package's root `index.ts`. `@pymalloy/core`
exposes compiler integration. Node and browser sessions create runtime-specific
`Model` interfaces and own their execution and lifetime. Keep implementation
classes, wire records, and conversion helpers private.

## Share language records across runtimes

`checkSource` composes parsing and semantic checking into one report, including
compiler version, source symbols, imports, diagnostics, query selectors, and
native schemas. Python, Node, and the compiler bridge consume this report.
`syntaxOnly` returns after parsing, before imports and schema discovery.

PyMalloy records use snake_case fields across language boundaries. Source
locations, annotations, imports, references, and given declarations have shared
shapes in core. A given has a string `type`, boolean `required`, and nullable
`default_text`. Python exposes check schemas through `analysis.NativeMetadata`.

`native` retains Malloy's model and source schema structures. Required givens can
defer whole-model query schemas, leaving `native.model` null while `native.sources`
remains available. Use PyMalloy records unless an adapter needs upstream schemas.

## Resolve imports and data separately

A model URL establishes source identity and the base for relative Malloy imports.
Node and Python readers accept local `file:` imports. Browser models use a virtual
URL namespace backed by their `files` mapping. A URL descriptor in that mapping
lets the browser fetch the mapped import or data file.

Python's `data_root` and Node's `dataRoot` set the base for relative data files,
independently of the import directory. Native adapters first resolve database
identifiers through DuckDB, including search paths and quoted names. SQL scope
identifies common table expressions (CTEs). A filename-shaped identifier can name
a real table. Preserve database identities before replacing relative file paths.

Python binds SQL through SQLGlot. Node binds DuckDB's serialized syntax tree.
Each uses one binding path for schema discovery and execution. Browser sessions
activate captured virtual files before discovery and queries. Test data access
changes at both boundaries.

## Give resources explicit lifetimes

| Resource                                                  | Owner and teardown                                                                                   |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Node connection and database instance                     | Session, when created by that session. `close()` drains submitted work and closes owned resources    |
| Browser worker, database, connection, and import requests | Session. Closing or a worker failure settles pending work, aborts imports, and terminates the worker |
| Python connection                                         | Session when created internally. A borrowed connection remains open with caller-owned transactions   |
| Deno process and compiled-model handles                   | Python session. Individual models release their handle, and session close shuts down the process     |
| Browser widget session                                    | anywidget model initialization. Initialization cleanup releases it                                   |
| Widget DOM and view listeners                             | Each rendered view. View cleanup detaches listeners and removes its DOM                              |
| Precompiled notebook query connection                     | One query cell. A context manager closes it after materializing the result or completing COPY        |
| Native notebook connection and compiler process           | The generated session, shared by the retained model and query cells                                  |

Native sessions serialize their operations. Callers lending a connection must
coordinate direct connection use with session work.

Python's `NativeRuntime` finalizer provides fallback cleanup for owned resources.
Use `close()` or context managers for deterministic cleanup. Models retain their
session. Borrowed connections remain caller-owned.

See [protocols and lifecycle](protocol.md) for widget revisions and operation deadlines.

## Preserve document meaning through export

Core parses `.malloynb` and `.malloysql` into ordered Markdown, Malloy, and SQL
statements. It retains source coordinates while compiling embedded Malloy
queries. A document request produces ordered `markdown` and `query` cells, with
DuckDB SQL in each query cell.

Python `compile_document` produces an immutable `Document`: title, ordered
`Markdown`/`Query` cells, data root, optional database, and a `precompiled`,
`native`, or `widget` profile. Native and widget documents include `ModelSource`
and normalized givens. Widget documents also retain local file aliases and
locations. `Query.kind` distinguishes `select` from `copy` for execution ordering.
Relative input and COPY destination paths refer to DuckDB's `data_root` variable.
The renderer configures that variable relative to the exported notebook's path.
All profiles discover schemas, bind givens, and validate selected SQL during
compilation. The generated notebook executes queries and COPY writes.

Precompiled renderers serialize SQL with DuckDB and Polars runtime dependencies.
Each query opens a connection, configures UTC and `data_root`, materializes its
result, and closes. Data persists in files or the database. Cells cannot share
temporary tables, connection settings, or transactions.

For native and widget profiles, core captures root text and the imports read
recursively, including definitions outside selected cells. Renderers serialize this
`ModelSource` and givens. Hydration reads captured source and discovers current
schemas. Original Malloy files are unnecessary, but referenced data must remain
accessible.

Native notebooks call `Session.load_source()`, then
`model.run(query=..., givens=givens)` per query. They depend on `pymalloy[server]`
pinned to the exporting version.

Widget compilation captures native file bindings during schema discovery and SQL
validation, including unselected SQL cells. Notebook setup reads resolved local
files as bytes and registers their original aliases. HTTP data remains URLs for
browser access. Reject native database state, COPY, globs, computed file paths,
and non-HTTP schemes before rendering.

Widget renderers emit one `Malloy` per selected query, or one for a model with no
query cells. Each receives `model_source`, `files`, and `givens` and exposes the
full query list. They depend on base `pymalloy` pinned to the exporting version.
Python creates the widget. Browser initialization starts schema discovery and
execution. Renderers own notebook syntax. The widget and session own execution
and cleanup.

Marimo cannot infer dependencies from SQL file writes. Its renderer adds a Python
dependency after each COPY so subsequent queries wait. Jupyter executes in
document order. Preserve both when changing document records.

The same source, schemas, options, output path, and dependency versions must
produce identical notebook bytes. Exclude timestamps, random identifiers, and
machine-specific metadata. Test through the kernel, including relative paths and
write/read ordering.

See [testing](testing.md) for runtime checks and [build and release](releasing.md)
for packaged assets.
