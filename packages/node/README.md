# @pymalloy/node

Run [Malloy](https://www.malloydata.dev/) models with native
[DuckDB](https://duckdb.org/) in Node.js 24.11 or newer.

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

Load files with `session.load(path)` or retain inline definitions with
`session.model(source)`. Results are row objects with nested structures and
JavaScript `bigint` values for large integers.

See the [Node API](../../docs/reference/node.md) for data access and lifecycle.
