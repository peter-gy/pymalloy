# Malloy for Node

Run Malloy on native DuckDB with an owned or borrowed connection.

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
columns, rows and a typed Malloy result for rendering. Active cancellation closes
the session. Use `AbortSignal.timeout(ms)` for a deadline.

[Node API](https://peter-gy.github.io/pymalloy/reference/node)
