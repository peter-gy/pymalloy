# Compiler API

`@malloy-runtime/compiler` drives Malloy through synchronous jobs. Each job returns
its result or requests source text and field schemas. Hosts own I/O and execution.

```ts
import { CompiledModel } from "@malloy-runtime/compiler";
import { drive, connection } from "@malloy-runtime/duckdb";

// host supplies readURL(URL) and describe(sql).
const model = await drive(
  CompiledModel.begin({
    url: new URL("file:///project/orders.malloy"),
    connection,
  }),
  host,
);
const prepared = await drive(model.prepare("orders.by_region"), host);
console.log(prepared.sql);
```

`CompiledModel.begin({url,source?,connection:{name,dialect}})` returns a `Job`.
`job.step(fulfilled?)` returns `{needs}` or `{result}`. Needs contain `urls` and
`schemas`. Every requested key must receive `{value}` or `{error}`. Schema values
are Malloy field definitions. A completed job rejects further steps. `close()`
releases an abandoned job.

Compiled models expose typed `queries`, `source()`, `inspect()`, `reference()`,
`prepare(selection?, {givens?})`, `defaultQueries()`, and
`document({queries?,all?,givens?})`. Preparation and document compilation return
jobs. Query names and source coordinates use zero-based ordinals.

`@malloy-runtime/compiler/tooling` exposes `parseSource`, `checkSource`,
`formatSource`, and `compilerVersion`. Checking returns a job. Parsing and
formatting are synchronous. Public records are available from
`@malloy-runtime/compiler/types`.

`@malloy-runtime/duckdb` converts DuckDB type strings to field definitions and
materializes native/Arrow values. The compiler takes connection identity and
dialect from its host and contains no database or filesystem APIs.
