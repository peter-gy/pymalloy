# Browser Python API

`pymalloy.browser` runs [Malloy](https://docs.malloydata.dev/) with
[DuckDB WebAssembly](https://duckdb.org/docs/stable/clients/wasm/overview.html)
from [Pyodide](https://pyodide.org/en/stable/), Python running in a browser.
The [browser Python guide](../guide/browser-python.md) covers installation and
first execution.

Default assets download from jsDelivr. The browser must permit asset fetches,
WebAssembly loading, and creation of DuckDB workers from `blob:` URLs. Opening
the first connection uses
Pyodide's [`run_js`](https://pyodide.org/en/stable/usage/api/python-api/code.html#pyodide.code.run_js)
to evaluate the packaged JavaScript runtime. Custom hosts must permit JavaScript
string evaluation in the Python worker. [Runtime assets](#runtime-assets)
configure matching self-hosted modules and workers.

<!-- not-executed -->

```python
from pymalloy import browser

async with browser.connect() as connection:
    model = await connection.model(
        "run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }"
    )
    result = await model.query().run()
print(result.to_pylist())
```

The result is `[{'answer': 42}]`. Remote data servers must permit cross-origin
requests from the notebook's origin.

## Connection

`browser.connect(*, runtime=None, name="duckdb", timeout=120) -> Connection`

Creates an owner for one browser DuckDB worker. Enter it with `async with`, or
retain the connection and await its operations directly. The first operation
opens the worker. `runtime` is a `browser.Runtime`. `name` identifies the Malloy
connection served by this worker. `timeout` must be a finite positive number of
seconds. `connection.name` and `connection.closed` report its identity and lifetime.

`await connection.close()` aborts and settles pending operations, closes child
models, and releases the worker. Repeated close calls are safe. Connections
require Pyodide. Native Python callers use [`pymalloy.connect`](runtime.md#connection).

### Compile a model

`await connection.model(source, *, files=None, url=None, document_kind=None, timeout=None) -> Model`

`source` accepts Malloy text, a `pathlib.Path` in Pyodide's filesystem, a `Draft`,
or a `ModelSource` snapshot. `url` sets the source identity for inline text.
Snapshots and drafts retain their source identity. A source `Path` reads the
root model text from Pyodide's filesystem. Supply its data and imported source
files through `files`. `document_kind` is `"model"` or `"notebook"`, inferred
from the source URL when omitted.

`files` maps virtual names to `bytes`, `bytearray`, `memoryview`, filesystem
`Path` values, or absolute HTTP(S) URL strings. Compilation snapshots the mapping
and local bytes. Remote bytes are fetched when needed and require cross-origin
permission. A `ModelSource` supplies its captured import closure. Other source
imports resolve through supplied files. URL-valued entries fetch source over
HTTP(S).

`timeout` sets both the compilation budget and the model's default operation
budget. Omission inherits the connection timeout. Compilation returns resolved
query descriptors and schemas. An unbound required given leaves that query's
output schema unresolved.

### Check, parse, and format

`await connection.check(source, *, files=None, url=None, document_kind=None, position=None, timeout=None) -> CheckReport`

Resolves names, types, imports, and file schemas. Source and file inputs follow
`model`. `position` accepts an optional `analysis.SourcePosition` with zero-based
line and character coordinates. The report contains structured diagnostics and
resolved metadata.

`await connection.parse(source, *, url=None, document_kind=None, timeout=None) -> ParseReport`

Parses source and returns syntax diagnostics and authored locations. It accepts
the same source types as `model`.

`await connection.format(source: str, *, timeout=None) -> str`

Formats Malloy model text and returns the formatted source. Invalid source
raises `CompilationError` with diagnostics.

`await connection.read_model(source, *, url=None, timeout=None) -> Draft`

Parses model text, a filesystem `Path`, or `ModelSource` into an editable,
immutable `Draft`. A path retains its file identity for subsequent saves in
Pyodide's filesystem. A snapshot retains its captured imports and input owners.
Structured editing accepts model grammar. Notebook documents require the parse,
check, or execution APIs.

## Model and query

`model.query(selection=None, *, malloy=None) -> Query`

Selects a query from `model.queries`. A string identifies a named query, saved
view, or ordinal such as `run:0`. A composed `Source` supplies an ad hoc query.
`malloy=` accepts ad hoc Malloy text. Omission selects the final run or the sole
available query. Ambiguous selection requires a name. Captured inputs in an
ad hoc source must already belong to the compiled draft.

`model.source() -> ModelSource` retains source identity, text, imports, and
captured inputs. The snapshot remains readable after closure. Data files still
need their file mapping when the snapshot is compiled in another connection.
`model.queries` contains immutable query descriptor records.
`model.compiler_version` identifies the Malloy compiler.

`await model.inspect(*, position=None, url=None, timeout=None) -> Inspection`

Returns the model inspection, including resolved schema and optional reference
at `position`. Coordinates use zero-based lines and Unicode code-point offsets.
`url` selects an imported source and requires `position`.

`model.close()` invalidates its queries and aborts its pending operations.
Sibling models remain usable. `model.closed` reports whether the model or its
connection has closed.

Query operations are asynchronous:

| Operation                                                     | Return value                                     |
| ------------------------------------------------------------- | ------------------------------------------------ |
| `await query.sql(*, givens=None, timeout=None)`               | Prepared SQL string                              |
| `await query.run(*, givens=None, timeout=None)`               | Materialized `browser.Result`                    |
| `await query.preview(*, limit=20, givens=None, timeout=None)` | Result limited to at most `limit` top-level rows |

Givens bind during SQL preparation. The mapping accepts finite numbers,
booleans, strings, nulls, and nested arrays and records. Python integers retain
exact precision. `Decimal`, `date`, and `datetime` values bind through their
text representations. Preview limits range from 1 to 10,000 and reject write
statements. Aggregation can scan the complete input even when its
output is bounded. Nested results can contain additional rows.

## Result

`browser.Result` retains detached materialized rows, SQL, and column metadata.
`result.sql` is the executed SQL. `result.columns` is a tuple of `Column` records
with `name` and DuckDB `type` strings.

`result.to_pylist() -> list[dict[str, object]]` returns fresh mutable containers.
It preserves exact Python integers, `decimal.Decimal`, and nested arrays and
records. Binary cells become lists of byte integers, such as `[0, 255]`.
Dates and timestamps use ISO text values. Results remain
readable after their model or connection closes. Conversion never reruns SQL.

Browser models, queries, and results can be displayed with
[`MalloyWidget`](widget.md) or left as notebook cell outputs. A widget borrows
its model's connection. Closing the widget preserves the model.

## Timeouts and errors

Operations serialize per connection. The timeout budget includes queue waiting,
opening, compilation, and execution. Cancellation takes effect at asynchronous
runtime boundaries. A synchronous JavaScript call must return before the Python
event loop can process cancellation. Cancelling the Python task aborts its
JavaScript operation and waits for it to settle before the next queued operation
proceeds. A timeout raises `TimeoutError`. Cancellation raises
`asyncio.CancelledError`.

Invalid input types or values raise `TypeError` or `ValueError`.
A closed owner raises `pymalloy.errors.ClosedError`. Failed model compilation,
query preparation, formatting, and structured model parsing raise
`CompilationError`, whose `diagnostics` retain source locations. `parse` and
`check` return diagnostics in their reports. Other browser runtime failures
raise `PyMalloyError`. A failed worker closes its connection. Create another
connection after worker failure.

## Runtime assets

`browser.Bundle(module: str, worker: str)` is a frozen pair of matching DuckDB
WebAssembly binary and worker URLs. Both URLs must be absolute HTTP(S) URLs.
Construction validates their shape. Browser loading checks availability.
Invalid types raise `TypeError`. Invalid URLs raise `ValueError`.

`browser.Runtime(mvp: Bundle, eh: Bundle | None = None)` selects the baseline
bundle and optional exception-handling bundle for compatible browsers. Pass it
as `runtime=` to `browser.connect` or `MalloyWidget`. It remains fixed for the
owner's lifetime. The asset servers must permit cross-origin requests and the
notebook's content security policy must permit the worker scripts.
