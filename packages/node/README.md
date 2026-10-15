# Malloy for Node

Run [Malloy](https://docs.malloydata.dev/) on native
[DuckDB](https://duckdb.org/docs/stable/), an embedded SQL engine, with an
owned or borrowed connection.

```ts
import { Session } from "@malloy-runtime/node";

const session = await Session.open();
try {
  const model = await session.model({
    text: "run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }",
  });
  console.log((await model.query().run()).rows);
} finally {
  await session.close();
}
```

Use `{path}` for a local model file or `{source: ModelSource}` for a captured
snapshot. `dataRoot` configures an owned connection's `file_search_path`.
Borrowed connections retain their caller's configuration and ownership.

Queries expose `sql({givens?})` and `run({givens?,signal?})`. Results contain SQL,
columns, rows and a typed Malloy result for rendering. Active cancellation
interrupts the operation and preserves the session after it settles. Use `AbortSignal.timeout(ms)` for a deadline.

`close()` stops new operations, interrupts an active statement, and drains accepted
queued operations before releasing owned resources. Borrowed connections remain
open. Results retain native rows. The `malloy` property creates rendering cells
on access, preserving exact integer and decimal text. TIME rows use bigint
microseconds since midnight. INTERVAL rows contain `months`, `days`, and bigint
`micros`. MAP rows contain `{key, value}` entries.

[Node API](https://peter-gy.github.io/pymalloy/reference/node)
