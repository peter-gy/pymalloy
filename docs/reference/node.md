# Node API

```ts
import { Session } from "@malloy-runtime/node";

const session = await Session.open({ dataRoot: "examples" });
try {
  const model = await session.model({ path: "examples/orders.malloy" });
  const query = model.query("orders.by_region");
  const sql = await query.sql();
  const result = await query.run({ signal: AbortSignal.timeout(30_000) });
  console.log(sql, result.columns, result.rows);
} finally {
  await session.close();
}
```

`Session.open({ dataRoot?, database?, connection?, connectionName? })` creates an owned or borrowed
native DuckDB session. A borrowed connection uses its caller's settings and
rejects `database` and `dataRoot` options. `connectionName` defaults to `"duckdb"`
and selects the Malloy connection name while keeping the DuckDB dialect.

`session.model(spec, { signal? })` accepts `{ text, url? }`, `{ path }`, `{ url }`,
or `{ source: ModelSource }`. Text specs also accept `documentKind`. Imports and URL models use local `file:` URLs.
`session.run(text, { givens?, signal? })` returns a materialized `Result`.

`session.check(text, { path?, syntaxOnly?, position?, signal? })` returns a report.
`session.format(text)` is synchronous. `close()` drains submitted work and closes
owned resources. Active cancellation interrupts that operation and waits for it
to settle before queued work starts. The session remains reusable. Queued
cancellation rejects that call.

Models expose `queries`, `query(selection?)`, `source()`, `inspect({position?,url?})`,
`document({queries?,all?,givens?})`, and `close()`. Select by name or `{ malloy }`.
Queries expose `name`, `kind`, `location`, `sql({givens?})`, and
`run({givens?,signal?})`. SQL and execution methods return promises.

Results contain `sql`, `columns`, `rows`, and `malloy`, the typed Malloy result
used for rendering. [Data resolution](../guide/data.md) follows native DuckDB rules.
