# Compiler API

`@malloy-runtime/compiler/jobs` compiles [Malloy](https://docs.malloydata.dev/)
through synchronous jobs. Each job returns its result or requests source text and
field schemas. Hosts own I/O and execution. Node and browser applications create
models through their [Session APIs](node.md).

```ts
import { readFile } from "node:fs/promises";
import { DuckDBInstance } from "@duckdb/node-api";
import { CompiledModel } from "@malloy-runtime/compiler/jobs";
import { drive, type Host } from "@malloy-runtime/compiler/adapters";
import { connection, describeSQL, fields } from "@malloy-runtime/duckdb";

const instance = await DuckDBInstance.create();
const database = await instance.connect();
try {
  const host: Host = {
    readURL: (url) => readFile(url, "utf8"),
    schema: async (need) => {
      const result = await database.runAndReadAll(describeSQL(need));
      return fields(
        result.getRowObjectsJS().map((row) => ({
          name: String(row.column_name),
          type: String(row.column_type),
        })),
      );
    },
  };
  const model = await drive(
    CompiledModel.begin({
      url: new URL("file:///project/model.malloy"),
      source: "run: duckdb.sql('SELECT 42 AS value') -> {select: value}",
      connection,
    }),
    host,
  );
  const prepared = await drive(model.prepare("run:0"), host);
  console.log((await database.runAndReadAll(prepared.sql)).getRowObjectsJS());
  // [{ value: 42 }]
} finally {
  database.closeSync();
  instance.closeSync();
}
```

`CompiledModel.begin({url,source?,documentKind?,connection:{name,dialect}})` returns a `Job`.
`job.step(fulfilled?)` returns `{needs}` or `{result}`. Needs contain `urls` and
`schemas`. Every requested key must receive `{value}` or `{error}`. Schema values
are Malloy field definitions. Table needs carry `{kind:"table", tablePath}` and
SQL needs carry `{kind:"sql", sql}`, both with a key and connection name. Hosts
construct any engine-specific schema probes. `documentKind` is `"model"` by default
or `"notebook"` for ordered notebook cells. A completed job rejects further steps. `close()`
releases an abandoned job.

Compiled models expose typed `queries`, `source()`, `inspect()`, `reference()`,
`prepare(selection?, {givens?})`, `defaultQueries()`, and
`document({queries?,all?,givens?})`. Preparation and document compilation return
jobs. `run:N` and `sql:N` use zero-based ordinals. Named queries retain their
authored names. Source positions use zero-based lines and Unicode code-point
columns. Parsed import spans use absolute code-point offsets.

`@malloy-runtime/compiler/adapters` is the host API. It exports `Host`, `drive`,
and `Runtime`. `drive(job, host)` fulfils a job's requests and closes it after
completion or failure. `Runtime` serializes adapter operations and owns their
cancellation and model lifetime.

`@malloy-runtime/compiler/tooling` exposes `parseSource`, `checkSource`,
`formatSource`, `syntaxSource`, and `compilerVersion`. `syntaxSource` projects
editable source bindings and scalar operations from Malloy's parser. Checking returns a job. Parsing and
formatting are synchronous. The root `@malloy-runtime/compiler` entry exports
the shared `Model`, `Query`, and `ToolingError` classes and application record types,
including `Result`, `QueryDescriptor`, `Inspection`, and `ModelSource`.

`@malloy-runtime/duckdb` provides `connection`, `fields`, `describeSQL`,
`fileSearchPath`, and `stableResult` for [DuckDB](https://duckdb.org/), the SQL
engine used by the adapters. `@malloy-runtime/duckdb/arrow` materializes Arrow
tables into rows. The compiler takes connection identity and
dialect from its host and contains no database or filesystem APIs.
