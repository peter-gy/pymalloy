# Browser JavaScript API

`@malloy-runtime/browser` compiles [Malloy](https://docs.malloydata.dev/documentation/)
models and runs SQL with [DuckDB WebAssembly](https://duckdb.org/docs/stable/clients/wasm/overview),
a database engine in a browser worker. Bundle the package with your application.

```ts
import { Session } from "@malloy-runtime/browser";

const session = await Session.open();
try {
  const model = await session.model({
    text: "run: duckdb.table('orders.csv') -> { aggregate: total is amount.sum() }",
    files: { "orders.csv": new TextEncoder().encode("amount\n20\n22\n") },
  });
  console.log((await model.query().run()).rows);
} finally {
  await session.close();
}
```

The result has `total` equal to exact decimal text `"42"`. Default assets download
from jsDelivr. The page must allow asset downloads, blob workers, and worker
script imports. Remote files and imports require
[cross-origin resource sharing](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS),
permission for the page's origin to read another server's responses.

## Exports

The root exports `Session`, `Model`, `Query`, and `ToolingError`, plus types
`SessionOptions`, `ModelSpec`, `DuckDBBundles`, `File`, `Files`, `Result`, `Row`,
`Value`, `QueryOptions`, `OperationOptions`, `QueryDescriptor`, `ModelSource`, and
`GivenValue`. Model and query contracts and class identity are shared with the
[Node adapter](node.md#model) and compiler package. The application bundler resolves
these runtime dependencies together.

## Session.open

`Session.open({bundles?, signal?, connectionName?} = {}): Promise<Session>`

`bundles` is DuckDB's bundle descriptor mapping. Omission selects versioned
jsDelivr modules and workers compatible with the browser. `signal` controls the
whole session lifetime, including opening. `connectionName` defaults to `duckdb`.
Owned workers and connections close on session failure or lifetime abort.
`session.closed: boolean` reports closure.

## Files and models

`File = Uint8Array | {url: string}` and `Files = Record<string, File>`.
Virtual names identify data or source text. Remote URLs must be browser-accessible.

`session.model(spec, {signal?} = {}): Promise<Model>` accepts
`{text, url?}`, `{url}`, or `{source: ModelSource}`. Each spec accepts
`files?: Files` and `documentKind?: "model" | "notebook"`.
Inline text defaults to `memory://pymalloy/model.malloy`. Model URLs determine
import resolution. The model snapshots file mappings and copies byte buffers
before queued work. Each model activates its own files for discovery and execution.
Captured source imports resolve exclusively through `ModelSource.imports`.

## Operations

| Method                                                                             | Contract                                                                                        |
| ---------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `run(text, {files?, givens?, signal?} = {})`                                       | Promise of a materialized result from the default query, closing the temporary model            |
| `check(text, {files?, url?, syntaxOnly?, documentKind?, position?, signal?} = {})` | Promise of a report. `syntaxOnly` defaults to false, and `url` defaults to the memory model URL |
| `format(text)`                                                                     | Synchronous formatted text. Formatter diagnostics throw `ToolingError` with `.diagnostics`      |
| `close()`                                                                          | Idempotent promise closing the worker and database and settling pending work                    |

`documentKind` overrides URL-based grammar inference. Positions are zero-based
Unicode code-point coordinates. Syntax checks report parser findings. Semantic
checks also resolve names, imports, and schemas. Compilation failures throw
`ToolingError`. Closed sessions, worker failures, and engine failures reject
operations with errors.

An operation signal cancels imports or the active query. Queued work resumes
after interruption settles. Worker failure, a session-lifetime abort, or `close()`
ends the session. Results remain materialized after closure.

Use `model.queries`, `model.query(selection?)`, `model.source()`,
`model.inspect({position?, url?})`, `model.document({queries?, all?, givens?, signal?})`,
and `model.close()` as defined in the [shared model contract](node.md#model).
Queries expose `name`, `kind`, `location`, `schema`, `sql({givens?, signal?})`, and
`run({givens?, signal?})`. Default selection uses the final run or the sole query.

Results expose `sql`, native `columns`, `rows`, and lazily rendered `malloy`.
[Arrow](https://arrow.apache.org/docs/), the columnar interchange format, carries
values out of the worker. Exact integers use bigint, decimals use text, dates
and timestamps use JavaScript `Date`, and lists and records stay nested.
Rendering non-finite numbers uses string cells while row numbers remain native.
