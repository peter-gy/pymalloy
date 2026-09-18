# Protocols and lifecycle

Widget and Python compiler messages are private contracts. Change both endpoints
and their consumer tests together.

## Widget input and state

`widget.py` owns the public `source`, `query`, `givens`, `files`, and `state`
traits. The synchronized input has two records:

| Record        | Fields                                                                | Publication                         |
| ------------- | --------------------------------------------------------------------- | ----------------------------------- |
| `_definition` | `revision`, `source`, `url`, `imports`, `files`                       | Construction, source or file change |
| `_input`      | `revision`, `definition_revision`, `query`, `givens`, `integer_paths` | Every validated input change        |

Before publishing, Python increments the input revision and resets public `state`
to `idle`. Source or file changes also increment the definition revision.
`_input.definition_revision` identifies the required definition. Query and given
updates reuse it. File text becomes UTF-8 bytes, carried as anywidget binary buffers.

For `ModelSource`, `source` holds root text, `url` preserves source identity, and
`imports` maps absolute URLs to captured text. String inputs use null `url` and
`imports` for browser defaults and file-based imports. Data files travel separately.

Construction sets `_runtime` from `pymalloy.browser.Runtime`, or null for browser
defaults. It selects DuckDB bundles for the widget's lifetime.

The query control writes `query`, then Python publishes an input snapshot.
Source and file changes publish both records. The frontend accepts a pair when
their definition revisions match.

`packages/widget/src/initialize.ts` owns one browser session per anywidget model
and one compiled model per definition revision. Query and given changes reuse
resolved definitions and schemas. Source or file changes release and replace the
model. The session activates captured files for schema discovery and execution.

Execution is serialized. New input replaces the single pending input and starts
a new publication generation. Publication requires the current generation and an
open widget. Results carry the input revision, letting Python reject late
messages. Obsolete work may finish but cannot replace the current result.

`_state` contains the public fields plus its revision and numeric transport
metadata:

| Field         | Shape                                                 |
| ------------- | ----------------------------------------------------- |
| `status`      | `idle`, `loading`, `ready`, `error`, or `closed`      |
| `queries`     | Array of available query selector strings             |
| `sql`         | SQL string or `null`                                  |
| `columns`     | Array of column-name strings                          |
| `rows`        | Array of records, including nested arrays and records |
| `diagnostics` | Array of compiler diagnostic records                  |
| `error`       | Error message or `null`                               |

Empty source is idle. With no query selected, a model stays idle if it has no
queries, or several choices with no default run. Compilation and execution
publish loading, then ready or error. Query errors preserve choices. Closing the
Python widget publishes `closed` and rejects future input assignments.

Python validates revision-matching results. Public `state` reads and observer
notifications contain detached copies with transport metadata excluded.

### Preserve numeric values

JSON cannot represent JavaScript `bigint`, NaN, or infinity. Payload paths such
as `[0, "nested", "count"]` identify values to reconstruct using record keys
and array indices.

| Direction                | Encoding                                                                                     | Reconstruction      |
| ------------------------ | -------------------------------------------------------------------------------------------- | ------------------- |
| Python givens to browser | Integers outside JavaScript's safe integer range become decimal strings with `integer_paths` | JavaScript `BigInt` |
| Browser rows to Python   | Every `bigint` becomes a decimal string with `integer_paths`                                 | Python `int`        |
| Browser rows to Python   | Non-finite numbers become `null` with `number_paths` entries tagged `nan`, `inf`, or `-inf`  | Python `float`      |

Row dates become ISO strings, binary views become byte arrays, and nested values
retain their structure. Views render at most 100 rows. Synchronization carries
the complete result, with no query or transport limit implied by the preview.

### Separate model and view cleanup

The anywidget `initialize` hook owns execution, input and definition listeners,
the retained model, and the browser session. Execution can start before `render`
creates a view. Each view owns its DOM, query control, and `_state`/`query`
listeners. Views share the initialized model, so removing one must preserve the
session for the others.

Initialization cleanup invalidates the generation, drops pending input, detaches
listeners, releases the model, aborts pending session creation, and closes the
session. While the widget remains open, new input can replace a failed session.

## Python compiler bridge

`server/_bridge.py` lazily starts one Deno process per session. Stdin/stdout carry
newline-delimited JSON, stderr carries process diagnostics. Deno runs bundled
`bridge.mjs` with read and environment permissions, cached dependencies, and
configuration loading disabled. The URL reader accepts local files. Captured
`load` requests supply root `source` text and resolve imports exclusively from
the absolute-URL-to-text `sources` mapping.

Each Python request has a monotonically increasing `id` and an `op`:

| Operation  | Result                                                                                      |
| ---------- | ------------------------------------------------------------------------------------------- |
| `load`     | Process-local model handle and query selectors                                              |
| `query`    | Query name, SQL, and source line when available                                             |
| `document` | Ordered Markdown and SQL query cells with givens bound, plus captured source when requested |
| `inspect`  | Model metadata and optional reference at a position                                         |
| `check`    | Shared check report and compiler version                                                    |
| `format`   | Formatted source and diagnostics                                                            |
| `release`  | Acknowledgment after removing the model handle                                              |

Bridge document requests select `precompiled` or `native`. Both return compiled
cells. `native` adds `source: {url, text, imports}` from core's `source()` snapshot.
Python requests captured source for both native and widget exports, then assigns
the public profile. Source URLs preserve diagnostic and import identities.
The hydrating session supplies data access.

The session lock permits one active request. Compilation can pause for schemas:

1. Python sends a request with `id`.
2. Deno sends `{id, kind: "schema", sql}`.
3. Python binds the SQL to the model's data root, runs `DESCRIBE` on its connection,
   and replies with `{id, columns: [{name, type}]}` or `{id, error}`.
4. Deno resumes compilation. It may request more schemas before sending a final
   `result` or `error` message with the same `id`.

Query rows stay in Python, materialized by DuckDB as Polars dataframes through
Arrow. Native givens use tagged decimal-string integers, recursive arrays, and
records. Deno decodes integers to `BigInt` before invoking Malloy.

### Distinguish recoverable and terminal failures

Compiler errors raise `CompilationError` with diagnostics and leave the session
usable. Broken JSON, mismatched IDs, unexpected response kinds, and process exit
raise a bridge `SessionError` and close the session.

Operation budgets cover lock acquisition and active work. A lock-wait timeout
leaves the active operation and session intact. An active timeout kills Deno,
interrupts DuckDB, and closes the session. Keyboard interruption during active
work also closes it. Borrowed connections stay open, but interrupted caller
transactions may have database effects the session cannot undo.

Model handles belong to their creating Deno process. Model close releases its
handle. Session close makes every handle unusable and closes an owned DuckDB
connection. Close is idempotent.

## Native Node operations

Node queues model loading, checking, formatting, SQL preparation, and execution.
The default budget is 120,000 milliseconds. Per-operation `timeout` and `signal`
cover queued and active work.

Queued aborts and timeouts reject that operation, leaving the session available.
Active aborts and timeouts reject pending work, interrupt DuckDB, and make the
session terminal. `close()` drains submitted work within its budgets and releases
owned connections and instances. Callers retain borrowed connections and must
handle interrupted transactions under DuckDB's rules.

The source reader receives the session's abort signal, so terminal failure aborts
file reads and database work. The runtime owns cancellation policy. Model
inspection reads retained compiler metadata synchronously.

## Source coordinates and diagnostics

Core normalizes diagnostic ranges to zero-based Unicode code-point positions
with an exclusive end. The document parser uses UTF-16 offsets, so core converts
its positions and maps embedded queries back to the authored document. Imported
diagnostics retain their imported URL. Ad hoc query text has its own source
identity.

Keep `code`, `message`, `severity`, `location`, and `replacement` consistent
between core reports, bridge errors, Python report records, and widget state.
Both `location` and `replacement` may be `null`. The widget converts coordinates
to one-based display labels without changing transported positions.
