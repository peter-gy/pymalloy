# Browser JavaScript API

`@pymalloy/browser` runs [Malloy](https://www.malloydata.dev/) with
[DuckDB WebAssembly](https://duckdb.org/docs/current/clients/wasm/overview).
Import it through your application's JavaScript bundler.

Creating a session downloads DuckDB's versioned assets from jsDelivr by default.
Allow those requests or supply self-hosted `bundles`. The page must allow `blob:` workers.
Include both `mvp` and `eh` bundles. Nested queries require `eh` and browser
WebAssembly exception handling support. The pinned `mvp` worker can fail on them
with `_setThrew is not defined`.

```typescript
import { Session } from "@pymalloy/browser";

const session = await Session.create();
try {
  const result = await session.run(`
    run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }
  `);
  console.log(result.rows); // [{ answer: 42 }]
} finally {
  await session.close();
}
```

## `Session.create(options = {})`

Returns `Promise<Session>`. A session owns its in-memory DuckDB database and
worker. Query execution starts in UTC.

| Option    | Contract                                                                       |
| --------- | ------------------------------------------------------------------------------ |
| `bundles` | DuckDB's `DuckDBBundles` configuration. Defaults to versioned jsDelivr assets. |
| `signal`  | Optional `AbortSignal` for the session's entire lifetime.                      |

Aborting `signal` rejects creation or closes an existing session, releasing
resources and rejecting outstanding work. Call `session.close()` when finished.
Creation captures bundle values and the signal reference when called.

### `session.run(source, options = {})`

Compile and execute Malloy source text. Returns `Promise<Result>`.

| Option    | Behavior                                                                                                                         |
| --------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `files`   | Mapping of virtual file paths to `Uint8Array` data or `{ url: string }`. Defaults to an empty mapping.                           |
| `url`     | Absolute root source URL for imports and diagnostics. Defaults to `https://pymalloy.local/model.malloy`.                         |
| `imports` | Optional mapping of absolute import URLs to captured source strings. When supplied, every import must be present in the mapping. |
| `query`   | Named query, `source.view`, or `run:N` selector. Defaults to the final run or single available query.                            |
| `givens`  | Per-call values declared in Malloy.                                                                                              |

Calls capture query selection and givens. Later option changes affect future
calls. Givens use Malloy's `GivenValue`
type, including nested records and arrays. Use JavaScript `bigint` for exact
integer inputs that exceed the safe range of `number`.

See [query selectors](/guide/models) for default selection and
[givens](/guide/givens) for Malloy declarations.

### Files and imports

File URLs must use HTTP or HTTPS. Remote servers must permit
[CORS](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS), the HTTP rules
for requests from another website.
Encode text, including imported Malloy models, as UTF-8:

```typescript
const session = await Session.create();
try {
  const result = await session.run("import 'base.malloy'\nrun: numbers -> { select: value }", {
    files: {
      "base.malloy": new TextEncoder().encode(
        "source: numbers is duckdb.sql('SELECT 42 AS value')",
      ),
    },
  });
  console.log(result.rows); // [{ value: 42 }]
} finally {
  await session.close();
}
```

Each model or run captures `url`, `imports`, and file inputs, copying bytes and
URL addresses. Imports resolve relative to their model URLs. Supply them in
`files`, or use `imports` for a complete source snapshot separate from data.
Loading can read remote imports and schemas. Execution can read remote data again.

A retained model keeps compiled imports, schemas, and registered files. Switching
models restores each one's file mapping, even for identical names with different
content. DuckDB caches HTTP data. Use versioned URLs for changed content, or a
new session for a fresh database and HTTP cache.

A virtual file path is a name inside the session, such as `data/orders.parquet`
or `models/base.malloy`. DuckDB uses the supplied file name, including absolute
paths and `../` segments. Directory names, query strings, fragments, and external
origins are rejected. For imports resolved through `files`, names resolve as URLs
relative to the root source. Use one unambiguous name per imported file.

### `Result`

`ResultRow` maps column names to `ResultValue`, the recursive union of supported
scalar, binary, date, list, and record values.

| Field     | Value                                         |
| --------- | --------------------------------------------- |
| `queries` | Available selector strings.                   |
| `sql`     | Compiled DuckDB SQL.                          |
| `columns` | Array of `{ name, type }` column descriptors. |
| `rows`    | Array of row objects.                         |

Nested arrays and records retain their structure. Result values use these
representations:

| DuckDB value                | JavaScript value                                             |
| --------------------------- | ------------------------------------------------------------ |
| Null                        | `null`                                                       |
| 64-bit and 128-bit integers | `bigint`                                                     |
| Decimal                     | Decimal string                                               |
| Date or timestamp           | `Date`, with millisecond precision                           |
| Binary                      | Typed byte array                                             |
| Map                         | Array of `{ key, value }` entries                            |
| NaN or infinity             | JavaScript `number` values `NaN`, `Infinity`, or `-Infinity` |

Column descriptors remain available for an empty result. Column `type` values
describe the [Arrow](https://arrow.apache.org/) columnar data format returned by
DuckDB, such as `Int64`. The complete result is materialized in browser memory.

## `session.model(source, options = {})`

Returns `Promise<Model>` with captured source and file inputs. `files`, `url`, and
`imports` match `session.run`. Loading discovers schemas and may read files or
contact remote servers before a query runs.

### `model.queries`

A read-only array of available query selector strings.

### `model.run(options = {})`

Returns `Promise<Result>` using the captured model. `query` and `givens` match
`session.run`. Each call captures its options and applies givens to that call.

### `model.run(source, options = {})`

Extends the captured model with Malloy source text for one query. Accepts
`givens` and returns `Promise<Result>`. Supplying both source text and a `query`
selector rejects the call. The retained model remains available for later calls.

### `model.inspect()`

Returns a detached, JSON-serializable description of the compiled model:

| Field                              | Contract                                                                                                              |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `native`                           | Malloy-native `model` and exported `sources` schemas. Model may be `null` when a query needs givens without defaults. |
| `queries`                          | Available query selectors.                                                                                            |
| `givens`                           | Declared `name`, type text, `required`, `default_text`, `location`, and annotations.                                  |
| `annotations`, `model_annotations` | Malloy annotations and their source locations.                                                                        |
| `dependencies`                     | Imported source URLs.                                                                                                 |
| `imports`                          | Records with `url` and `location`.                                                                                    |
| `diagnostics`                      | Compiler messages, including warnings.                                                                                |

Inspection reads compiled metadata without executing queries. Annotations attach
metadata to definitions. Their reference identifiers can change between compilations.

### `model.close()`

Releases the retained model. Repeated calls are safe. Subsequent calls to `run`
reject, and `inspect` throws. Obtain models through `session.model()` and import
`Model` as a TypeScript type when annotating application code.

## `session.close()`

Returns a promise, releases models, closes the database, and terminates the
worker. Outstanding and future work reject. Repeated calls are safe.
`session.closed` reports closure. Session calls are serialized.

Compilation and query failures leave the session available. Worker failures
close it and require a new session.

## Errors and diagnostics

Compiler errors reject with an error containing a `diagnostics` array. Each
diagnostic has `code`, `severity`, `message`, `location`, and `replacement`, with
nullable `data` and `error_tag` fields. Severity is `error`, `warning`, or `debug`.

A location is `null` or `{ url, range: { start, end } }`. Each position contains
zero-based `line` and `character` offsets counted in Unicode code points. The
end is exclusive. `replacement` is `null` or suggested source text for the range.
Keep the URL when displaying or applying a diagnostic from an imported model.

Query selection, data access, and execution can reject with an ordinary `Error`
without diagnostics. Display its `message` and revise the input before retrying.
