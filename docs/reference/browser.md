# Browser JavaScript API

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

`Session.open({ bundles?, signal?, connectionName? })` creates a DuckDB WebAssembly worker and
connection. Defaults use versioned jsDelivr assets. `bundles` accepts DuckDB's
bundle descriptors. The opening signal controls session lifetime.

`session.model(spec, {signal?})` accepts `{text,url?,documentKind?,files?}`,
`{url,files?}`, or `{source:ModelSource,files?}`. Files map virtual names to
`Uint8Array` or `{url}`. HTTP(S) downloads require CORS. Each model owns a snapshot
of its file mapping. Captured imports resolve exclusively from `ModelSource`.

`session.run(text, {files?,givens?,signal?})`, `check(text, options)`, `format(text)`,
and the Model/Query/Result API follow the [Node contract](node.md). Browser check
options include `files`, `url`, `syntaxOnly`, `position`, and `signal`.

An operation signal cancels its imports or active query, then queued work resumes
after cancellation settles. Worker failure, the opening signal, or `close()` ends
the session and settles pending work. `close()` is idempotent. Rows preserve bigint, Decimal text, dates, nested records, and arrays.
