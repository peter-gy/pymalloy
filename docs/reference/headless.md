# Headless Python API

```python
import pymalloy as pm

result = (
    pm.connect()
    .model("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }")
    .query()
    .run()
)
print(result.to_pylist())
```

Install `pymalloy[headless]` for headless execution.

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
operation budget in seconds. `compiler_memory_mb` bounds each compiler's V8 heap.

`connection.model(source, *, url=None, document_kind=None, timeout=None)` compiles
Malloy text, a `Path`, `ModelSource`, or `Draft`. Paths and snapshots supply their
identity. A conflicting `url` raises `ValueError`. `document_kind` selects model
or notebook grammar and otherwise follows the source identity.

`connection.duckdb` exposes the native connection. Coordinate direct engine use
with runtime operations. `connection.name` and `connection.closed` report identity
and lifetime. `connection.close()` settles work, closes every child model, then
closes the owned engine. Context management scopes this lifetime. Models and
queries retain their connection. Each model owns one compiler process and can
close independently while sibling models remain usable.

## Model and Query

`model.queries` contains `QueryDescriptor(name=..., kind=..., location=...)` records.
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
`pm.parse(source, *, url=None, document_kind=None)` returns a typed `ParseReport` with `ok` derived from error diagnostics, syntax metadata,
imports, and table references. It includes `compiler_version`. Each parsed import
retains its statement location and a `reference` span locating its quoted URL
in Unicode codepoints. `ParsedImport` and `SourceSpan` are available from
`pymalloy.analysis`. `document_kind` selects `"model"` or `"notebook"`, with
URL-based inference when omitted.

Formatting, parsing, syntax projection, and checking share one serialized tooling
compiler process. It shuts down after 30 idle seconds, and the next call starts
another process. Checks resolve source and schemas afresh on every call. Their
timeout includes waiting for the compiler lease. Formatting and parsing have a
30-second deadline and open no DuckDB connection.

## Result and errors

`result.sql` is the executed SQL. `columns` is a tuple of frozen
`Column(name=..., type=...)` records shared with schema discovery.
The engine materializes an Arrow table once. `to_arrow()` returns that table without
copying its buffers. `to_pylist()` materializes detached Python dictionaries.
`to_polars()` requires a separately installed `polars` and preserves Arrow chunks where supported.
Results remain readable after model cleanup.

`PyMalloyError` is the common base for PyMalloy failures:

- `CompilationError` carries diagnostics for invalid Malloy source or unresolved schemas.
- `ClosedError` identifies a closed connection or model.
- `CompilerError` identifies an internal compiler or transport failure.
- `ExecutionError` retains the original DuckDB query exception in `__cause__`.
- `SchemaError` retains the failed schema probe and engine exception.
- `ValidationError` carries a rejected validation in `report`.

Import these exceptions from `pymalloy.errors`. `PyMalloyError` is also available at the root.

Invalid options raise `TypeError` or `ValueError`. Expired deadlines raise
`TimeoutError`. A SQL timeout interrupts the statement and leaves a healthy model
available. A queued timeout leaves active work running. An in-flight compiler
request timeout stops the compiler process and closes its model, as do compiler
crashes and heap exhaustion. Create a new model after compiler failure.

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
