# Malloy in the browser

Run Malloy with a DuckDB WebAssembly worker and model-specific virtual files.

```ts
import { Session } from "@malloy-runtime/browser";

const session = await Session.open();
try {
  const model = await session.model({
    text: "run: duckdb.table('data.csv') -> { select: value }",
    files: { "data.csv": new TextEncoder().encode("value\n42\n") },
  });
  console.log((await model.query().run()).rows);
} finally {
  await session.close();
}
```

`Session.open({bundles?,signal?,connectionName?})` configures worker assets and session lifetime.
Models accept text, a URL, or `ModelSource` plus virtual files. URL descriptors
require CORS. Models share the compiler's Model/Query/Result contract with Node.

[Browser API](https://peter-gy.github.io/pymalloy/reference/browser)
