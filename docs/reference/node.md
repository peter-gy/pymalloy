# Node API

`@malloy-runtime/node` compiles [Malloy](https://docs.malloydata.dev/documentation/)
semantic models and runs their SQL on native [DuckDB](https://duckdb.org/docs/stable/),
an analytical database. Use Node 24.11 or newer.

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

The rows are `[{ answer: 42 }]`. The package root exports `Session`, `Model`,
`Query`, and `ToolingError`, plus types `SessionOptions`, `ModelSpec`,
`CheckOptions`, `Result`, `Row`, `Value`, `QueryOptions`, `OperationOptions`,
`QueryDescriptor`, and `ModelSource`. `Model`, `Query`, and `ToolingError` are the
same classes exported by `@malloy-runtime/compiler` and the browser adapter.

## Session.open

`Session.open(options: SessionOptions = {}): Promise<Session>`

| Option                          | Default and behavior                                        |
| ------------------------------- | ----------------------------------------------------------- |
| `dataRoot?: string`             | Current directory. Sets the owned engine's file search path |
| `database?: string`             | In-memory database. Opens the supplied native database path |
| `connection?: DuckDBConnection` | Borrow an existing `@duckdb/node-api` connection            |
| `connectionName?: string`       | `duckdb`, the Malloy connection name                        |

Owned sessions set UTC and `file_search_path` before schema discovery.
Borrowed connections preserve caller settings and lifetime and reject `database`
and `dataRoot`. Configure and coordinate direct engine use yourself.
`session.connection` exposes the native engine and `session.closed` reports
whether it accepts further operations.

## session.model

`session.model(spec: ModelSpec, options: OperationOptions = {}): Promise<Model>`

`ModelSpec` is one of these shapes, each also accepting `documentKind?: "model" | "notebook"`:

| Spec                           | Source identity                                             |
| ------------------------------ | ----------------------------------------------------------- |
| `{text: string, url?: string}` | Inline text. Default URL is `model.malloy` under `dataRoot` |
| `{path: string}`               | Local path resolved from the current directory              |
| `{url: string}`                | Source loaded from a local `file:` URL                      |
| `{source: ModelSource}`        | Root text and closed imports from the snapshot              |

`options.signal` cancels compilation and imports. File extension infers document
kind unless overridden. Relative imports follow the model URL. Captured imports
must all exist in their mapping. Source identity and data lookup are separate.
The model retains discovered schemas. Recompile after source or schema changes.

## Model

Models are created by `session.model`.

| Member                                              | Return and behavior                                                                                                                   |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `queries`                                           | Read-only query descriptor array with `name`, `kind`, `location`, and optional output `schema`                                        |
| `query(selection?: string \| {malloy: string})`     | `Query`. Omitted selects the last run or sole query. An ambiguous selection throws                                                    |
| `source()`                                          | Detached `ModelSource` with `url`, `text`, `imports`, and `documentKind`                                                              |
| `inspect({position?, url?} = {})`                   | Synchronous inspection with schemas, givens, annotations, dependencies, and optional reference lookup. `url: URL` requires a position |
| `document({queries?, all?, givens?, signal?} = {})` | Promise of ordered Markdown and query cells. `queries` and `all` conflict. Empty `queries` retains prose and source inventory         |
| `close()`                                           | Synchronously invalidates this model and its queries. Sibling models and the session remain usable                                    |

Kinds are `run`, `named`, `view`, and `sql`. `source.view` selects a public source
view. `run:N` and `sql:N` use zero-based authored ordinals. Required unbound givens
can leave query output schema `null`. Source schemas live separately in inspection.
`model.query({malloy: "run: orders -> detail"})` compiles an ad hoc selection.
Query descriptors keep output schemas on the descriptor itself.

## Query and result

`query.sql(options: QueryOptions = {}): Promise<string>` prepares SQL.
`query.run(options: QueryOptions = {}): Promise<Result>` executes and materializes
it. Both accept `givens?: Record<string, GivenValue>` and `signal?: AbortSignal`.
Bindings apply to one call. Queries read current data and retain their parent
model. `name`, `kind`, `location`, and `schema` describe the selection.

`Result` has `sql: string`, `columns: Column[]`, `rows: Row[]`, and `malloy`, a
Malloy result tree computed when accessed. Columns have native `name` and `type`.
Rows are field-name mappings with scalar, array, and nested record values.
Results remain readable after closure.

| Native row type     | Representation                                                  |
| ------------------- | --------------------------------------------------------------- |
| Exact large integer | `bigint`                                                        |
| Decimal             | Exact decimal text                                              |
| Date and timestamp  | JavaScript `Date`                                               |
| TIME                | `bigint` microseconds since midnight                            |
| INTERVAL            | `{months, days, micros}`, with bigint microseconds              |
| MAP                 | Array of `{key, value}` entries, preserving exact nested values |

The native driver truncates timestamp microseconds to milliseconds. For
`TIMESTAMP '2024-02-03 04:05:06.123456'`, rendering cells contain
`"2024-02-03T04:05:06.123Z"`. Rendering fields containing non-finite numbers use
string values for that field. `rows` and `columns` retain native numbers and types.

## Check, format, and close

`session.check(text, {path?, syntaxOnly?, documentKind?, position?, signal?} = {})`
returns `Promise<CheckReport>`. `path` sets source identity, defaulting to
`model.malloy` under `dataRoot`. `syntaxOnly` defaults to false.
`documentKind` overrides filename inference. Positions use zero-based lines and
Unicode code-point columns. Semantic checks resolve imports and schemas.
Source problems are returned in report diagnostics.

`session.run(text, {givens?, signal?} = {})` creates a model, runs its default
query, and closes that model before returning `Promise<Result>`.

`session.format(text): string` uses Malloy's experimental formatter. Formatter
diagnostics throw `ToolingError`, whose `.diagnostics` carries the native findings.
Compilation failures also throw `ToolingError`. Engine errors retain native
exceptions. Invalid options and closed resources throw errors.

`session.close(): Promise<void>` is idempotent. It stops accepting operations,
interrupts an active statement, drains accepted queued work, invalidates models,
and releases owned resources. Borrowed engines stay open. An operation signal
rejects queued work or interrupts active work. Queued operations resume after
interruption settles, and healthy sessions remain reusable. A failed interrupt
makes the session terminal.
