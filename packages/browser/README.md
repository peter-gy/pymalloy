# @pymalloy/browser

Run [Malloy](https://www.malloydata.dev/) with
[DuckDB WebAssembly](https://duckdb.org/docs/current/clients/wasm/overview) in a browser.

```typescript
import { Session } from "@pymalloy/browser";

const session = await Session.create();
try {
  const result = await session.run("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }");
  console.log(result.rows); // [{ answer: 42 }]
} finally {
  await session.close();
}
```

The default runtime downloads versioned WebAssembly and worker assets from
jsDelivr. The page must permit their network requests and worker execution.
Provide model and data files as `Uint8Array` values or HTTP URL descriptors.

See the [browser API](../../docs/reference/browser.md) for files, result types,
custom bundles, and lifecycle.
