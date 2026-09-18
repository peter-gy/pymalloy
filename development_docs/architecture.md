# Architecture and ownership

Malloy owns language semantics. Compiler jobs request source text and field
schemas. Hosts fulfil those requests and execute the resulting SQL with DuckDB.

## Follow a query

1. A host calls `CompiledModel.begin` with source identity, optional inline text,
   and a connection name and dialect.
2. `Job.step()` drives `MalloyTranslator.translate()`. It returns a result or
   import/schema needs. The next step receives an answer for every requested key.
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
| `packages/server`                            | Deno compiler service and framed process entry point                                                  |
| `pymalloy._server`                           | Deno process, Python DuckDB engine, model ownership and deadlines                                     |
| `pymalloy.widget`                            | Python inputs and detached widget snapshots                                                           |
| `pymalloy.export`                            | Export validation, COPY destination anchoring and notebook serialization                              |
| `apps`                                       | Documentation and notebook-host acceptance tests                                                      |

## Source and data

`ModelSource` is a closed source snapshot: root URL, root text, and imported text
keyed by URL. A virtual translator root keeps inline text distinct from an
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

| Resource                        | Owner and teardown                                                      |
| ------------------------------- | ----------------------------------------------------------------------- |
| Owned native connection         | Python model or TypeScript session, closed after submitted work settles |
| Borrowed native connection      | Caller, including settings and transactions                             |
| Browser worker and database     | Session, terminated on close, worker failure, or active abort           |
| Import requests                 | Session abort controller                                                |
| Deno process and compiler job   | Python model, released on close or collection                           |
| MalloyWidget session            | anywidget initialization, released by initialization cleanup            |
| MalloyWidget DOM and renderer   | Rendered view, listeners and visualization disposed on cleanup          |
| Precompiled notebook connection | Query cell, closed after materialization or COPY                        |
| Server notebook model           | Generated setup shared by query cells                                   |

Operations serialize per Python model or TypeScript session. Queued cancellation
rejects that call. Active cancellation interrupts execution and closes its owner. TypeScript accepts
`AbortSignal`, including `AbortSignal.timeout(ms)`. Python measures seconds across
lock acquisition, compilation and execution. Compiler requests receive the remaining
budget. Active cancellation kills Deno and interrupts DuckDB.
`compiler_memory_mb` limits the compiler V8 heap, independently of DuckDB memory. `pm.run` closes resources before returning. Retained Python models use finalizer
cleanup and expose `close()` for early release. Queries keep their model alive.

## Records and rendering

`@pymalloy/protocol` holds Python wire records. The widget and server import it,
and it imports compiler types. The compiler and database adapters never import
the protocol or either Python-facing adapter. Deno uses its native Web APIs and
loads a self-contained bundle from the wheel. Source reads and schema discovery
remain in Python.

TypeScript records use camel case. `tools/generate-records.py` emits JSON Schema
from compiler and widget types, then generates Python msgspec records with Python
field names and wire aliases. Dictionary keys containing authored names remain
unchanged. Validate incoming data at the boundary with those generated records.

The widget publishes a Malloy stable Result. Numeric cells retain exact text for
bigint and Decimal values. Non-finite values carry their spelling in `string_value`
with a finite numeric placeholder for JSON. Python decodes cells with their
schema. The renderer consumes the Malloy result and its annotations. The widget copies
renderer styles into its own view for shadow-root hosts and supplies table roles
to the renderer DOM. View cleanup disconnects both observers.

Malloy's experimental formatter remains isolated in `core/src/upstream.ts`.
Translation metadata comes from the translator and the model definition produced
by the job, rather than private fields on parsed or compiled objects.

## Repeated work and result conversion

A compiled model owns one typed query registry. Embedded queries retain their
validated preparation and SQL fragments, so first execution uses the schemas
already discovered during compilation. Each call binds its own givens
and executes against current data. SQL-only calls leave rendering metadata
unevaluated. Ad hoc source is translated for each request.

Browser models keep a bounded output-schema cache keyed by SQL and the returned
Arrow schema. Schema changes invalidate the entry. Dictionary schemas and large
keys bypass the cache. Cache entries contain column descriptions, not rows.
Model file snapshots copy input buffers once before queued work starts.

Arrow materialization plans decoders per field and reads column vectors directly.
Stable result conversion patches exact scalar values in its owned cell tree.
Python Arrow conversion builds columns directly from retained values and caches
immutable type schemas. Reading Python rows still returns detached values.
Compiler replies use generated tagged records. Public syntax reports and document
cells keep those typed records instead of crossing another dictionary boundary.
Python snapshots copy containers through msgspec while preserving immutable native
scalars such as Decimal, dates, UUIDs, and bytes. Unvalidated trait inputs retain
Python copying behavior until validation accepts or rejects them.

Idle Deno processes exit through stdin EOF so Deno can persist its code cache.
Active failures terminate the child immediately. Graceful shutdown has a bounded
wait before termination. Export preflight shares one compiler across source imports.

MalloyWidget query selection updates its control immediately. Result publications own
rendering. Each retained model supplies diagnostics once, and view observers
update styles and accessibility roles only where the DOM changed. Non-finite
numbers copy their changed result branches before being passed to the renderer.
Browser result publications disable anywidget's echo message. The browser already
owns that result, and Python still validates and publishes its detached state.

## Notebook exports

Compiler documents preserve Markdown, Malloy and SQL order, including embedded
query splicing and authored diagnostics. `Document` carries public givens, files,
source, profile and ordered cells.

A shared typed notebook plan owns execution profiles, setup, query naming and
COPY dependencies. Marimo and Jupyter serializers supply format-specific syntax.
Export preparation carries one deadline through every phase.

Precompiled notebooks set `file_search_path` and the `data_root` variable on each
connection. The exporter anchors relative COPY destinations using that variable.
Server notebooks hydrate `ModelSource` and use `model.query(name).run()`. MalloyWidget
notebooks create `MalloyWidget` instances from source and registered files. The exporter
uses public model, parse, and connection methods.

MalloyWidget file discovery uses Malloy table-path metadata. Readers inside SQL require
explicit `files`. MalloyWidget exports reject COPY and native database state.
Marimo serialization adds Python dependencies after COPY. Jupyter executes cells
in order. Identical inputs, schemas, options, output paths and dependencies must
produce identical notebook bytes.
