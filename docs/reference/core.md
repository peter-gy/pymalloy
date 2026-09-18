# Compiler API

`@pymalloy/core` compiles Malloy to SQL. The host reads model URLs, discovers
schemas, and executes the SQL. Use the [Node](/reference/node) or
[browser](/reference/browser) API for a runtime with data access included.

```typescript
import { CompiledModel } from "@pymalloy/core";

const model = await CompiledModel.load({
  url: new URL("memory://example/answer.malloy"),
  source: "run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }",
  describe: async () => [{ name: "answer", type: "INTEGER" }],
  readURL: async (url) => {
    throw new Error(`No imported model is available at ${url.href}`);
  },
});

const query = await model.query();
console.log(query.name); // run:1
console.log(query.sql);
```

The example supplies its SQL literal's known schema. Runtime adapters must
discover schemas using the same connection and data-path rules as execution.

## `CompiledModel.load(options)`

Returns `Promise<CompiledModel>` after loading source, resolving imports, and
discovering schemas.

| Option     | Contract                                                                    |
| ---------- | --------------------------------------------------------------------------- |
| `url`      | Required `URL` identifying the root model and the base for imports          |
| `source`   | Optional inline text. When omitted, the root is read through `readURL`      |
| `describe` | Required `(sql: string) => Promise<Column[]>` callback for schema discovery |
| `readURL`  | Required asynchronous function returning text for a `URL`                   |

The URL suffix selects document parsing for `.malloynb` and `.malloysql`.
Other source is parsed as Malloy. Supported models use the `duckdb` connection.
The host decides which URL protocols and locations are accessible.

`Column` contains `name: string` and a DuckDB `type: string`, such as `INTEGER`
or `VARCHAR`. In `describe`, run DuckDB's `DESCRIBE` against the supplied query
and return its column names and types. The host owns connections, file binding,
credentials, and cleanup.

Compilation may read imports and data for schemas. Query execution belongs to the
host. Colliding query selectors fail loading with an error naming the ambiguity.

## `model.queries`

A frozen array of available query selector strings. It includes unnamed runs,
named queries, public views on exported sources, and document SQL cells.
See [query selectors](/guide/concepts#queries-and-selectors) for their spelling
and default selection.

## `model.query(selector?, source?, givens?)`

Returns `Promise<{ name: string; sql: string; line?: number }>`.
`selector` chooses an existing query. `source` supplies full Malloy query text,
including `run:`, and takes precedence when present. `givens` supplies a mapping
of Malloy `GivenValue` values for this compilation.

With neither source nor selector, the final run statement is selected, or the
single available query. `line`, when present, is the zero-based line in the
authored document. Inline query extensions have the name `query`.

The returned SQL may include file references. The host must apply its data
access rules before execution. Document SQL cells require the `duckdb` connection
and may contain `COPY` writes. The runtime adapter owns SQL validation and execution.

## `model.document(selectors, givens?)`

Returns `Promise<Cell[]>` for notebook or document rendering. `selectors` is a
string array. An empty array selects defaults. An array containing `"*"`
selects every available query.

```typescript
type Cell = { kind: "markdown"; text: string } | { kind: "query"; name: string; sql: string };
```

For a Malloy model, defaults select all run statements, then named queries if
there are no runs, then public source views. For an authored document, defaults
retain Markdown and executable cells in authored order. Explicit selection
returns query cells in selection order. A source-only model produces a Markdown
inventory of its sources.

`givens` applies to every selected query, using declared defaults for omitted
values. Generated SQL captures the values. The host executes queries and writes.

## `model.source()`

Returns a detached `SourceBundle` containing the original root source and every
import captured while loading the model:

```typescript
interface SourceBundle {
  url: string;
  text: string;
  imports: Record<string, string>;
}
```

`url` identifies the root document. `text` preserves its authored `.malloy`,
`.malloynb`, or `.malloysql` source. `imports` maps absolute URLs to source.
Reload with the root URL,
`source: bundle.text`, and `readURL` backed by `bundle.imports`.
Reloading discovers current schemas through `describe`.

## `model.inspect()`

Returns an `Inspection` containing JSON-compatible compiler metadata:

| Field                              | Content                                                                             |
| ---------------------------------- | ----------------------------------------------------------------------------------- |
| `native.model`                     | Native model metadata, or `null` when required givens defer query schemas           |
| `native.sources`                   | Native exported source schemas                                                      |
| `queries`                          | Available selectors                                                                 |
| `givens`                           | Names, type descriptions, required status, default text, locations, and annotations |
| `annotations`, `model_annotations` | Annotation records with route, text, content, and location                          |
| `dependencies`                     | Imported source URLs                                                                |
| `imports`                          | Import targets and locations                                                        |
| `diagnostics`                      | [Compiler diagnostics](#errors-and-diagnostics)                                     |

Each given has `name`, `type`, `required`, `default_text`, `location`, and
`annotations`. `type` describes the declared type, such as `number`, `string[]`,
`{tenant :: string}`, or `filter<string>`. `required` is true when the declaration
has no default. `default_text` preserves the authored expression, including
references to other givens, and is `null` when no default exists. Locations are
nullable. Annotation records contain `route`, `text`, `content`, and `location`.

`native` follows the bundled Malloy compiler's schema. Annotation reference IDs
can change between compilations. Compare inspections using semantic fields.

## `model.reference(position)`

Accepts `{ line, character, url? }` and returns a `ReferenceInfo` object with
`reference` and `import` fields. Each is `null` when the position has no match.
`url` is a `URL` selecting an imported document and defaults to the root model.

A reference contains `text`, `kind`, `location`, `definition_location`,
`definition_type`, `default_text`, and `annotations`. An import contains `url`
for its target and `location` for its occurrence in the importing document.
Positions use nonnegative, zero-based lines and Unicode code points, with an
exclusive range end. Invalid position coordinates raise `RangeError`.

## Language tools

### `parseSource(source, options = {})`

Returns a `ParseReport` with `url`, `diagnostics`, `symbols`, `tables`, `imports`,
`completions`, and `help`. Parses text without loading imports or discovering schemas.

`options.url` defaults to `memory://pymalloy/model.malloy`. Set a document suffix
to parse `.malloynb` or `.malloysql`. `options.position` requests native
completion text and contextual help. Document parsing includes embedded Malloy
queries. Standalone SQL still requires database validation.

### `checkSource(options)`

Accepts `LoadOptions` plus optional `position` and `syntaxOnly` and returns a
`Promise<CheckReport>`. The report includes every `ParseReport` field plus `ok`,
`compiler_version`, `native`, and `queries`. `position` requests contextual help
and completions. `syntaxOnly: true` checks the root source without resolving
imports or schemas. It leaves `native.model` null, `native.sources` empty, and
`queries` empty.

Syntax errors stop semantic checking. Language diagnostics appear in the report.
Host I/O and unexpected errors can reject. Semantic checks may access imports and data.

### `formatSource(source)`

Returns `{ source, diagnostics }` using Malloy's experimental formatter. When
syntax errors occur, `source` retains the input text. Review formatted output
before writing it to an authored file.

### `compilerVersion`

The bundled Malloy compiler's version string. Record it alongside diagnostics
or native metadata when another process consumes those reports.

## Errors and diagnostics

`ToolingError` extends `Error` and carries `diagnostics: Diagnostic[]` for native
compiler failures. Selection and host failures can be ordinary errors. Preserve
the original diagnostic location when showing or applying an edit to imported source.

Each `Diagnostic` has `code`, `severity`, `message`, `location`, and `replacement`.
Severity is `error`, `warning`, or `debug`. Location and replacement are nullable.
`error_tag` and `data` preserve additional native diagnostic information and are
`null` when absent. Diagnostic dictionaries use these same names across runtimes.
Locations contain a URL and a range of zero-based Unicode code-point positions.
