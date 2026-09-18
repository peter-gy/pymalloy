# Protocols and lifecycle

## Compiler jobs

Core jobs run synchronously. `step()` returns `{needs:{urls,schemas}}` or
`{result}`. Each schema need carries a key, connection, SQL, and optional table
path. `step(fulfilled)` requires a value or error for every requested key.
Errors from source and schema discovery become Malloy diagnostics with authored
locations. Hosts decide whether fulfilment is synchronous or asynchronous.

## Python compiler process

`packages/protocol` defines requests and tagged replies. `packages/server` owns one
compiled model and one pending compiler job per process. Python starts the executable
returned by the optional `deno` distribution's `find_deno_bin()`. It runs the
wheel's self-contained `server.mjs` with local configuration, npm resolution,
and remote imports disabled. Deno receives no filesystem or network permissions.

Each frame contains a four-byte unsigned big-endian length followed by UTF-8
JSON, bounded to 64 MiB. Startup returns `{kind:"ready"}`. Operations serialize
per Python model, with one response per request. Reply kinds are `needs`, `error`,
`model`, `query`, `document`, `inspection`, `source`, `check`, `parse`, and `format`.
Generated msgspec records validate the complete reply before it reaches the Python
caller, which checks the expected result type. Python fulfils source and schema
needs between requests. SQL result rows remain in Python.

Operations are `begin`, `step`, `query`, `inspect`, `source`, `document`, `check`,
`parse`, and `format`. A new operation closes an abandoned job. A `step` requires
a pending job. The compiled model remains available until process close.
Python sends DuckDB column descriptions and the server converts them to compiler
field definitions. Expected engine schema failures become compiler diagnostics.
Unexpected host failures remain exceptions.

The process owner manages framed I/O, a bounded stderr buffer, and teardown.
Timeouts terminate the compiler process and interrupt DuckDB. Queued operations
that time out before acquiring the model operation lock leave active work running.
Closing reaps the child and closes its pipes. Compiler crashes become
`ModelError`, while source and schema errors remain `CompilationError` with
source diagnostics. Widgets create no compiler process.

## MalloyWidget synchronization

| Trait         | Shape                                                           | Published when              |
| ------------- | --------------------------------------------------------------- | --------------------------- |
| `_definition` | revision, source, URL, imports, files                           | Source or files change      |
| `_input`      | revision, definitionRevision, query, typed givens               | Any validated input changes |
| `_state`      | revision, status, query descriptors, result, error, diagnostics | Browser work progresses     |
| `_runtime`    | DuckDB WebAssembly bundles                                      | MalloyWidget construction   |

Python validates inputs before publishing them. Definition and input revisions
travel separately. The browser waits until `input.definitionRevision` matches
`definition.revision`. It keeps a single running operation and coalesces pending
inputs to the most recent one.

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

Givens use a tagged recursive protocol shared by Python server execution and the
widget. Integers travel as exact decimal text. Arrays and records recursively
contain tagged values.

Results use Malloy's stable schema and cell tree. Bigints use `subtype: "bigint"`
and exact `string_value`. Decimal cells retain their string value. NaN and
infinities use their spelling in `string_value`, with a finite `number_value` for
JSON transport. Python validates the generated record shape and decodes values
against their schema. Public snapshots are detached from synchronized state.

Regenerate records with `uv run python tools/generate-records.py` after changing
the TypeScript contracts, then rebuild widget and compiler assets before testing
the installed wheel.
