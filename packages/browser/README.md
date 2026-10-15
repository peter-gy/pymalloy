# Malloy in the browser

Run [Malloy](https://docs.malloydata.dev/) with a
[DuckDB WebAssembly](https://duckdb.org/docs/stable/clients/wasm/overview.html)
browser SQL worker and model-specific virtual files.

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
require CORS. Models share the compiler's Model/Query/Result contract with Node, including
class identity. The application bundler resolves the browser package's runtime
dependencies. `pnpm canary` installs packed packages, checks their declarations,
and executes the packed browser bundle through the browser acceptance test.

[Browser API](https://peter-gy.github.io/pymalloy/reference/browser)
