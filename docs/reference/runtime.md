# Python runtime API

[Malloy](https://docs.malloydata.dev/documentation/) compiles semantic queries.
[DuckDB](https://duckdb.org/docs/stable/) executes SQL on the native connection.
For Python running in Pyodide, use the asynchronous
[browser Python API](browser-python.md).

```python
import pymalloy as pm

with pm.connect() as con:
    result = con.model(
        "run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }"
    ).query().run()
print(result.to_pylist())
assert result.to_pylist() == [{"answer": 42}]
```

## Connection

`pm.connect(database=":memory:", *, data_root=None, read_only=False, config=None,
extensions=(), name="duckdb", timeout=120, compiler_memory_mb=256) -> Connection`

Pass a database path to own a native DuckDB connection, or pass an existing
DuckDB connection to borrow it. Borrowed connections preserve caller settings,
registrations, and transactions. They reject `data_root`, `read_only=True`,
`config`, and nonempty `extensions`.

A failed statement, including a timeout, can abort an open borrowed transaction.
Subsequent operations report the aborted transaction. The caller must
issue `ROLLBACK` before reusing it. PyMalloy leaves `COMMIT` and `ROLLBACK` to
the connection owner.

`name` is the Malloy connection name. `data_root` sets the owned connection's
file search path. `config` supplies native DuckDB settings. `extensions` are
installed and loaded before file-access restrictions. `timeout` is the default
operation budget in seconds. `compiler_memory_mb` sets each compiler's managed
[V8](https://v8.dev/) JavaScript heap budget. It excludes native allocations and
is separate from DuckDB memory settings. Managed heap exhaustion closes the
affected model. The compiler runs inside Python, so a fatal V8 failure can
terminate the Python process. Use a separate application process when compiler
crash containment is required.

`connection.model(source, *, url=None, document_kind=None, timeout=None)` compiles
Malloy text, a `Path`, `ModelSource`, or `Draft`. Paths and snapshots supply their
identity. A conflicting `url` raises `ValueError`. `document_kind` selects model
or notebook grammar and otherwise follows the source identity.

`connection.duckdb` exposes the native connection. Coordinate direct engine use
with runtime operations. `connection.name` and `connection.closed` report identity
and lifetime. `connection.close()` settles work, closes every child model, then
closes the owned engine. Context management scopes this lifetime. Models and
queries retain their connection. Each model owns an embedded compiler on a
dedicated thread and can close independently while sibling models remain usable.

Connections and compiler owners belong to the process that created them. Use
`multiprocessing` with its `spawn` start method for child work. After `fork`,
connection and model operations raise `ClosedError`, and compiler tooling raises
`CompilerError`, before acquiring inherited PyMalloy locks. PyMalloy cleanup
abandons inherited owners.

## Model and Query

`model.queries` is a tuple of `pymalloy.analysis.QueryDescriptor` records with
`name`, `kind`, `location`, and output `schema`. Required unbound givens can yield
`schema=None`. Source schemas live separately in `model.inspect().model.sources`.
`model.query(selection=None, *, malloy=None)` accepts a named query or a composed
`Source`. Use `malloy=` for native Malloy query text.
Omit both to select the final run or single available query.

`query.run(*, givens=None, timeout=None)` executes a selected query.
`query.sql(*, givens=None, timeout=None)` prepares its SQL.
`query.preview(*, limit=20, givens=None, timeout=None)` bounds top-level returned
rows and rejects COPY. `limit` must be an integer from 1 to 10,000. Aggregation
can still scan the full input, and nested
results can contain additional rows.

`model.inspect(*, position=None, url=None, timeout=None)` returns `Inspection`.
`model.source()` returns a `ModelSource` retaining logical text, imported source,
and captured input owners. Compile that snapshot after closing the original model
to reuse its captured data.
`model.document(*, queries=None, all=False, givens=None, timeout=None)` returns an
ordered tuple of typed `MarkdownCell` and `QueryCell` records. `queries=None` uses
the default selection. `queries=[]` selects no query cells. Authored Markdown or a
source inventory may remain.
Passing query names together with `all=True` is invalid.
`model.compiler_version` reports the compiler packaged with this runtime.
`model.closed` reports whether execution is available.

## Language tools

`connection.check(source, *, url=None, document_kind=None, position=None,
documentation=None, timeout=None)` returns a `CheckReport` with compiler diagnostics
and schema metadata. Pass a documentation policy for
[documentation lint](authoring.md#documentation-policy).

`connection.validate(draft, checks=None, *, givens=None, documentation=None,
timeout=None)` captures bindings once and executes counterexample queries.
One deadline covers compilation, inspection, and all checks.

`pm.format(source)` returns formatted source using the compiler.
`pm.parse(source: str | Path | ModelSource | Draft, *, url=None, document_kind=None)` returns a typed `ParseReport` with `ok` derived from error diagnostics, syntax metadata,
imports, and table references. It includes `compiler_version`. Each parsed import
retains its statement location and a `reference` span locating its quoted URL
in Unicode codepoints. `ParsedImport` and `SourceSpan` are available from
`pymalloy.analysis`. `document_kind` selects `"model"` or `"notebook"`, with
URL-based inference when omitted.

Native wheels include formatting, parsing, `read_model`, and syntax projection.
These operations and connection checks lease a serialized tooling compiler with
its own dedicated thread. It closes after 30 idle seconds, and the next call
creates another compiler. Checks resolve source and schemas afresh on every
call. Their timeout includes waiting for the compiler lease. Formatting and
parsing have a 30-second deadline and open no DuckDB connection.

## Result

`result.sql` is the executed SQL. `columns` is a tuple of frozen
`Column(name=..., type=...)` records shared with schema discovery.
The engine materializes an [Arrow](https://arrow.apache.org/docs/) columnar table
once through [PyArrow](https://arrow.apache.org/docs/python/), its Python library. `to_arrow()` returns that table without
copying its buffers. `to_pylist()` materializes detached Python dictionaries.
`to_polars()` requires separately installed [Polars](https://docs.pola.rs/), a dataframe library, and preserves Arrow chunks where supported.
Results remain readable after model cleanup.

`result.__arrow_c_stream__(requested_schema=None)` implements the
[Arrow PyCapsule stream protocol](https://arrow.apache.org/docs/format/CDataInterface/PyCapsuleInterface.html).
Consumers such as `polars.DataFrame(result)` and `pyarrow.table(result)` read the
retained buffers. Conversions execute against materialized data and preserve its
schema, including empty SELECT results. COPY results have empty rows and columns.
`pymalloy.result.Column(name=..., type=...)` is a frozen native column record.

## ModelSource

`pm.ModelSource(url, text, imports=None, document_kind=None, *, inputs=())`

Construct an immutable closed source graph. `url` is an absolute identity,
`text` is logical source text, `imports` maps absolute URLs to source text, and
`inputs` is a tuple of `pymalloy.authoring.Input` owners. `imports=None` becomes
an empty mapping. Captured imports are immutable and must contain every referenced
import. Compilation resolves that graph. The kind is `"model"` or `"notebook"`,
inferred from the URL when omitted. Conflicting identity or invalid shapes raise
`TypeError` or `ValueError`. External table data remains a runtime dependency.

## Errors

`PyMalloyError` is the common base for PyMalloy failures:

- `CompilationError` carries diagnostics for invalid Malloy source or unresolved schemas.
- `ClosedError` identifies a closed connection or model.
- `CompilerError` identifies an internal compiler or native boundary failure.
- `ExecutionError` retains the original DuckDB query exception in `__cause__`.
- `SchemaError` retains the failed schema probe and engine exception.
- `ValidationError` carries a rejected validation in `report`.

Import these exceptions from `pymalloy.errors`. `PyMalloyError` is also available at the root.

Invalid options raise `TypeError` or `ValueError`. Expired deadlines raise
`TimeoutError`. A SQL timeout interrupts the statement and leaves a healthy model
available. A queued timeout leaves active work running. An in-flight compiler
request timeout terminates the active JavaScript work and closes its model.
Managed heap exhaustion and compiler boundary failures also close the model.
Create a new model after compiler failure. Deadlines cover compiler startup,
queue waiting, source and schema requests, SQL preparation, and execution.
Interruption settles active work before its owner accepts another operation.
Native engine stalls can delay teardown beyond the managed execution budget.

`ExecutionError.context` is detached from the live model. It exposes `source`
(the captured model and imports), `query` (`QueryDescriptor`), `malloy` (ad hoc
query text, when supplied), generated `sql`, `givens`, `compiler_version`,
`connection_name`, and `preview_limit`. The `givens` mapping is read-only and captures the bindings used by the compiler.
The context remains readable after model closure. Replay with
`pm.connect(name=context.connection_name).model(context.source)` against the same
data and connection settings.

Schema-discovery failures retain `SchemaError` as the cause of `CompilationError`.
Its `sql` is the DESCRIBE statement, and its own cause is the original engine
exception. Compiler diagnostics remain on `CompilationError.diagnostics`.

`Inspection.model.annotations` enumerates source and field paths with native
annotation routes, payloads and original text. Malloy parses routes, including
`#"` descriptions and application routes such as `#(research)`. The upstream
stable model and source metadata remain available alongside this projection.
