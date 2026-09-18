# @pymalloy/core

Compile [Malloy](https://www.malloydata.dev/) models into DuckDB SQL using a
host-provided URL reader and schema discovery callback.

```typescript
import { CompiledModel } from "@pymalloy/core";

const model = await CompiledModel.load({
  url: new URL("https://models.example/answer.malloy"),
  source: "run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }",
  describe: async () => [{ name: "answer", type: "INTEGER" }],
  readURL: async (url) => {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Model request failed: ${response.status}`);
    return response.text();
  },
});
const query = await model.query();
console.log(query.sql);
```

The example supplies the schema of its SQL literal. Runtime adapters provide
`describe(sql)` against their database and execute the returned SQL.

`parseSource(source, { url, position })` returns syntax diagnostics, symbols,
imports, table paths, completions, and help context. `checkSource(options)` accepts
the same inputs as `CompiledModel.load`, plus `position` and `syntaxOnly`, and
returns a report with source metadata and diagnostics.
`formatSource(source)` adapts Malloy's experimental formatter and returns source
with syntax diagnostics.

`model.inspect()` exposes givens, annotations, dependencies, and diagnostics,
with native schemas under `native`. `model.reference({ line, character, url })` resolves a use site or
import to its definition. Positions use zero-based Unicode code points.

Use [@pymalloy/node](../node/README.md) for native Node execution or
[@pymalloy/browser](../browser/README.md) for browser execution.
See the [Compiler API](../../docs/reference/core.md) for arguments and result
contracts, and [architecture and ownership](../../development_docs/architecture.md)
for contributor guidance.
