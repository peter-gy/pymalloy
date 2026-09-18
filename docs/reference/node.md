# Node API

`@pymalloy/node` runs Malloy in [Node.js](https://nodejs.org/) with the
native [DuckDB client](https://duckdb.org/docs/stable/clients/node_neo/overview):

```typescript
import { Session } from "@pymalloy/node";

const session = await Session.create();
try {
  const rows = await session.run("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }");
  console.log(rows); // [{ answer: 42 }]
} finally {
  await session.close();
}
```

Requires Node 24.11 or newer. Queries return arrays of row objects, preserving large
integers as `bigint` and nested results as arrays and records.

## `Session.create(options = {})`

Create a session with an owned DuckDB connection or borrow an existing connection.
Returns `Promise<Session>`.

| Option       | Behavior                                                                                                  |
| ------------ | --------------------------------------------------------------------------------------------------------- |
| `dataRoot`   | Directory for relative data paths. Defaults to the loaded file's parent or inline model's base directory. |
| `database`   | Database file to open. Defaults to an in-memory database.                                                 |
| `connection` | Existing DuckDB Node connection to borrow. Pass it independently of `database`.                           |
| `timeout`    | Operation budget in milliseconds, including queue time. Defaults to `120000`.                             |

`session.connection` is a read-only property exposing the native connection. Owned connections start in UTC.
Borrowed connections retain their settings and remain caller-owned after the
session closes. Coordinate direct connection operations with session queries.

### `session.model(source, { baseDir, timeout, signal } = {})`

Load inline definitions and return `Promise<Model>`. `baseDir` sets the directory
for imports and defaults to `dataRoot` when supplied, then the working directory.

### `session.load(path, { timeout, signal } = {})`

Load a local `.malloy`, `.malloynb`, or `.malloysql` file. Returns `Promise<Model>`.
Imports read local files relative to their importing model.

### `session.run(source, options = {})`

Load inline Malloy source, execute a query, and release the temporary model.
Use `options.query` to select a query and `options.givens` for per-call values.
Returns `Promise<Row[]>`. `Row` maps column names to the native DuckDB client's
JavaScript value types. Relative data paths use `dataRoot`
when supplied, otherwise the working directory.
Calls capture their selector and givens when submitted.
`timeout` overrides the session budget and `signal` accepts an `AbortSignal`.

### `session.check(source, options = {})`

Return a `CheckReport`. `options.path` identifies the draft and resolves imports,
defaulting to `inline.malloy` under `dataRoot` or
the working directory. `syntaxOnly: true` parses before accessing imports or
data. `position: { line, character }` requests completions and contextual help.
`timeout` and `signal` control this operation.

```typescript
import { Session } from "@pymalloy/node";

const session = await Session.create();
try {
  const report = await session.check("run: unknown_source", { path: "draft.malloy" });
  console.log(report.ok); // false
  console.log(report.diagnostics[0].location);
} finally {
  await session.close();
}
```

See [CheckReport fields](/reference/core#checksource-options). Semantic checking
discovers schemas using the session's data access. Standalone SQL cells require
DuckDB validation. Language errors appear in the report.

### `session.checkFile(path, options = {})`

Read a local Malloy file or document and check it. Options match `check()` except
that the file supplies `path`. File access errors reject the returned promise.

### `session.format(source, { timeout, signal } = {})`

Return formatted source using Malloy's experimental formatter. Malformed source
rejects with `ToolingError` and its diagnostics. Review output before writing
authored files.

### `session.close()`

Wait for queued operations, then release models and owned database resources.
Calls on a session are serialized. Repeated close calls return the same promise.
Await closure in a `finally` block so failures also release the session.
`session.closed` becomes true when closure begins and new work is rejected.

## `Model`

`session.model()` and `session.load()` return retained models. Import their type with:

```typescript
import { Session, type Model } from "@pymalloy/node";
```

### Run a query

```typescript
import { Session } from "@pymalloy/node";

const session = await Session.create();
try {
  const numbers = await session.model("source: numbers is duckdb.sql('SELECT 42 AS value')");
  const rows = await numbers.run("run: numbers -> { select: value }");
  console.log(rows); // [{ value: 42 }]
} finally {
  await session.close();
}
```

`model.run(source, options)` accepts query source and per-call options.
Use `model.run({ query: "orders.by_region" })` to select an existing query, or
supply `givens` in that options object for typed per-call values. Reload the model
after changing its schema or imported definitions.

`model.queries` is a frozen array of available selectors: named queries, public
`source.view` names, one-based `run:N` statements, and document `sql:N` cells.
With no source or selector, `model.run()` executes the final run statement or the
single available query. Multiple choices require a selector. Each call captures
its selector and givens when submitted.

### `model.sql(source?, options = {})`

Compile a query and return executable SQL with data paths resolved. Select a
query with `model.sql({ query, givens, timeout, signal })` or supply full `run:`
source as the first argument. Selection and bindings match `model.run()`.
Compilation leaves result execution and `COPY` writes to the caller.

### `model.inspect(options = {})`

Return [compiled metadata](/reference/core#model-inspect) using the model's
captured schemas. Required givens can leave `native.model` as `null` while
`native.sources` remains available.
Pass `position: { line, character }` for reference and import lookup. An optional
`url: URL` selects an imported document and requires a position. Positions use
zero-based Unicode code points with an exclusive end. Inspection is synchronous.

### `model.close()`

Release the model synchronously. Running a closed model or submitting work after
session closure rejects.

## Errors and data access

Import `ToolingError` from `@pymalloy/node` to recognize compiler failures with
structured diagnostics. Execution errors reject with the native DuckDB error.
Language and query errors leave the session available. Borrowed connections keep
the caller's transaction state, including rollback requirements after a failure.

Schema discovery and execution use the same connection and data root. Database
identifiers take precedence over file-like names. Remote data requires DuckDB's
network access and any credentials or extensions its reader needs.

## Timeouts and cancellation

`timeout` is a positive, finite number of milliseconds up to `2147483647`.
It covers time waiting in the queue and active compilation, schema discovery,
and execution. JavaScript timers cannot interrupt synchronous JavaScript in the
middle of a call. The budget is checked again when that work returns.

Every asynchronous session/model operation accepts a per-call `signal`.
Aborting or timing out while queued rejects that call and leaves the active
operation and session intact. Aborting or timing out during active work interrupts
DuckDB, closes the session, and rejects its queued work. Await `session.close()`
before reusing a borrowed connection after interruption.

Timeouts reject with an error named `TimeoutError`. Signal cancellation uses its
error reason, or an `AbortError`. Create a new session after active cancellation.
Borrowed connections remain caller-owned, including their transaction recovery.
