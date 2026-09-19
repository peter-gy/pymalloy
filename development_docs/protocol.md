# Protocols and lifecycle

## Compiler jobs

Core jobs run synchronously. `step()` returns `{needs:{urls,schemas}}` or
`{result}`. Each schema need carries a key and connection. A `kind: "table"`
need supplies `tablePath`, while a `kind: "sql"` need supplies SQL. The host builds
the dialect-specific schema probe. `step(fulfilled)` requires a value or error
for every requested key.
Errors from source and schema discovery become Malloy diagnostics with authored
locations. Hosts decide whether fulfilment is synchronous or asynchronous.

## Python compiler process

`packages/protocol` defines requests and tagged replies. `packages/headless` owns one
compiled model and one pending compiler job per process. Python starts the executable
provided by the optional Python `deno` distribution. It runs the
wheel's self-contained `headless.mjs` with local configuration, npm resolution,
and remote imports disabled. Deno receives no filesystem or network permissions.

Each frame contains a four-byte unsigned big-endian length followed by UTF-8
JSON, bounded to 64 MiB. Startup returns `{kind:"ready"}`. Operations serialize
per Python model, with one response per request. Replies report needs, errors,
or the requested result. Diagnostic failures use `{kind:"error",message,diagnostics}`.
Internal compiler failures use `{kind:"failure",message}`.
`packages/protocol/src/headless.ts` defines the tagged request and response unions.
Generated msgspec records validate the complete reply before it reaches the Python
caller, which checks the expected result type. Python fulfils source and schema
needs between requests. SQL result rows remain in Python.

`begin` starts compilation with an explicit connection name, dialect, and document
kind. `step` fulfils pending needs. Query, inspection,
source, and document operations use the retained model. Check, parse, format,
and syntax projection operations process supplied text. A new operation closes
an abandoned job. A `step` requires a pending job. The compiled model remains available until process close.
Python sends DuckDB column descriptions and the Deno host converts them to compiler
field definitions. Expected engine schema failures become compiler diagnostics.
Unexpected host failures remain exceptions.

A Python model owns its compiler process. Format, parse, syntax projection, and
check calls lease one shared tooling compiler, with serialized requests and a
30-second idle shutdown. Lease acquisition and startup consume the caller's
deadline. Each check resolves imports and schemas afresh. Failed processes are
discarded, and subsequent tooling calls start a new process.

The process owner manages framed I/O, bounded stderr capture, and teardown.
An in-flight compiler request timeout terminates the process. A SQL timeout interrupts the
active statement and leaves a healthy model usable. A queued timeout leaves the
active operation running. Closing reaps the child and closes its pipes. Internal
compiler and transport failures become `CompilerError`, while source and schema
errors remain `CompilationError` with diagnostics. Both derive from
`PyMalloyError`. Widgets create no compiler process.

## MalloyWidget synchronization

| Trait         | Shape                                                               | Published when              |
| ------------- | ------------------------------------------------------------------- | --------------------------- |
| `_definition` | revision, source, URL, documentKind, connectionName, imports, files | Source or files change      |
| `_input`      | revision, definitionRevision, query, typed givens                   | Any validated input changes |
| `_state`      | revision, status, query descriptors, result, error, diagnostics     | Browser work progresses     |
| `_runtime`    | DuckDB WebAssembly bundles                                          | MalloyWidget construction   |

Python validates inputs before publishing them. Definition and input revisions
travel separately. The browser waits until `input.definitionRevision` matches
`definition.revision`. It keeps a single running operation and coalesces pending
inputs to the most recent one. A new input aborts the superseded operation and
waits for its interruption to settle before starting the replacement.

A generation counter binds every publication to the current input. Late work
cannot replace current state. Python retains the last accepted wire frame across
trait validation and resynchronization. The renderer independently requires the
result revision to match the current input.
A source change releases the previous model. Query and given changes reuse it.
A failed worker closes the session, and a subsequent input creates another one.

Initialization owns the session and input listeners. View rendering owns DOM,
query controls, state listeners and the Malloy visualization. Both cleanup paths
are idempotent. Closing aborts imports and worker work, settles requests and
prevents further publication.

## Values

Givens use a tagged recursive protocol shared by Python headless execution and the
widget. Integers travel as exact decimal text. Arrays and records recursively
contain tagged values.

Widget results use Malloy's stable schema and cell tree. Native Python results
stay in the engine adapter and do not use this transport. Bigints use `subtype: "bigint"`
and exact `string_value`. Decimal cells retain their string value. NaN and
infinities use their spelling in `string_value`, with a finite `number_value` for
JSON transport. Python validates the generated record shape and decodes values
against their schema. Public `state`, `files`, and `givens` use immutable mappings
and tuples, detached once at publication. Reads and observers reuse those values.
The synchronized traits retain ordinary JSON containers. `analysis.to_dict`
explicitly materializes dictionaries and lists for consumers that need them.

Regenerate records with `uv run python tools/generate-records.py` after changing
the TypeScript contracts, then rebuild widget and compiler assets before testing
the installed wheel.
