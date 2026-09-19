# Headless Python API

```python
import pymalloy as pm

result = pm.run("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }")
print(result.rows())
```

Install `pymalloy[headless]` for headless execution.

## model

`pm.model(source, *, url=None, data_root=None, database=None, connection=None,
config=None, extensions=(), connection_name="duckdb", document_kind=None,
read_only=False, timeout=120, compiler_memory_mb=256)` compiles a
reusable `Model`.

- `source`: Malloy text, a `pathlib.Path`, `Draft`, or `ModelSource`. Strings always mean text.
- `url`: identity and import base for inline source.
- `document_kind`: `"model"` or `"notebook"`. Defaults to the source snapshot
  kind, or infers notebooks from `.malloynb` and `.malloysql` identities.
- `data_root`: data search directory for an owned DuckDB connection.
- `database`: persistent DuckDB database path.
- `connection`: caller-owned DuckDB connection. Configure its settings and extensions yourself.
- `config`: native DuckDB configuration for an owned connection. Defaults include
  UTC and a file search path rooted at `data_root` or the working directory.
  Explicit timezone and file-search settings take precedence. `data_root` and
  `config["file_search_path"]` are mutually exclusive.
- `extensions`: sequence of extension names to install and load on an owned
  connection. Installation, loading, and native credential initialization happen
  before external-access restrictions and configuration locking are applied.
  Startup work consumes the operation deadline.
- `connection_name`: Malloy connection name served by this DuckDB connection.
- `read_only`: open a persistent database for reading.
- `timeout`: seconds available for construction and compilation, and the default for subsequent operations.
- `compiler_memory_mb`: compiler V8 heap limit in MiB, independent of DuckDB memory.

A borrowed `connection` rejects `config`, nonempty `extensions`, `database`,
`data_root`, and `read_only=True`. Capture Python dataframe inputs with
`pm.data(frame)` in a draft.

A model owns its compiler process and any connection it creates. Queries retain
the model. Resources are released when the model becomes unreachable.
`model.close()` releases them immediately and is idempotent. Models also support
`with pm.model(source) as model:` for scoped ownership. Borrowed connections
retain caller ownership, settings, and transactions.

## run

`pm.run(source, *, givens=None, **model_options)` runs the default query and
returns a materialized `Result`. It accepts the options of `pm.model` and closes
its temporary model before returning, including on failure. Its timeout covers
construction, compilation, and execution.

## Model and Query

`model.queries` contains `QueryDescriptor(name, kind, location)` records.
`model.query(selection=None, *, malloy=None)` accepts a named query or a composed
source/query `Fragment`. Use `malloy=` for native Malloy query text.
Omit both to select the final run or single available query.

`model.run(*, givens=None, timeout=None)` and `model.sql(*, givens=None,
timeout=None)` use that default query. Named selections expose the same methods
through `query.run(...)` and `query.sql(...)`.
`query.preview(*, limit=20, givens=None, timeout=None)` bounds top-level returned
rows and rejects COPY. `limit` must be an integer from 1 to 10,000. Aggregation
can still scan the full input, and nested
results can contain additional rows.

`model.inspect(*, position=None, url=None, timeout=None)` returns `Inspection`.
`model.source(*, timeout=None)` returns `ModelSource`.
`model.document(*, queries=None, all=False, givens=None, timeout=None)` returns an
ordered tuple of typed `MarkdownCell` and `QueryCell` records. `queries=None` uses
the default selection. `queries=[]` selects no query cells. Authored Markdown or a
source inventory may remain.
Passing query names together with `all=True` is invalid.
`model.compiler_version` reports the compiler packaged with this runtime.
`model.connection` exposes the DuckDB connection. Coordinate direct connection use
with model operations. `model.closed` reports whether execution is available.

## Language tools

`pm.check(source, *, path=None, url=None, connection_name="duckdb", document_kind=None, syntax_only=False,
position=None, data_root=None, database=None, connection=None, config=None,
extensions=(), read_only=False, timeout=120, compiler_memory_mb=256)` returns a compiler `CheckReport` and
closes any data connection it creates. Source accepts the same types as `pm.model`.
`path` and `url` are mutually exclusive source-identity options. A draft supplies
its own identity by default. `syntax_only=True` skips import and schema resolution.

`pm.check` reports compiler diagnostics. Pass a documentation policy to
`Draft.check(documentation=...)` to add
[documentation lint](authoring.md#documentation-policy).

`pm.format(source)` returns formatted source using the compiler.
`pm.parse(source, *, url, document_kind=None)` returns a typed `ParseReport` with syntax metadata,
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

`result.sql` is the executed SQL. `columns` is a tuple of `Column(name, type)`.
The engine materializes an Arrow table once. `arrow()` returns that table without
copying its buffers. `rows()` materializes detached Python dictionaries.
`polars()` requires a separately installed `polars` and preserves Arrow chunks where supported.
Results remain readable after model cleanup.

`PyMalloyError` is the common base for PyMalloy failures:

- `CompilationError` carries diagnostics for invalid Malloy source or unresolved schemas.
- `ModelError` identifies a closed model.
- `CompilerError`, a `ModelError` subclass, identifies an internal compiler or transport failure.
- `ExecutionError` retains the original DuckDB query exception in `__cause__`.
- `SchemaError` retains the failed schema probe and engine exception.

Invalid options raise `TypeError` or `ValueError`. Expired deadlines raise
`TimeoutError`. A SQL timeout interrupts the statement and leaves a healthy model
available. A queued timeout leaves active work running. An in-flight compiler
request timeout stops the compiler process and closes its model, as do compiler
crashes and heap exhaustion. Create a new model after compiler failure.

`ExecutionError.context` is detached from the live model. It exposes `source`
(the captured model and imports), `query` (`QueryDescriptor`), `malloy` (ad hoc
query text, when supplied), generated `sql`, `givens`, `compiler_version`,
`connection_name`, and `preview_limit`. Each `givens` read returns a detached dictionary of the bindings
used by the compiler. The context remains readable after `pm.run()` closes its
model. Replay with `pm.model(context.source, connection_name=context.connection_name)`
against the same data and connection settings.

Schema-discovery failures retain `SchemaError` as the cause of `CompilationError`.
Its `sql` is the DESCRIBE statement, and its own cause is the original engine
exception. Compiler diagnostics remain on `CompilationError.diagnostics`.

`Inspection.model.annotations` enumerates source and field paths with native
annotation routes, payloads and original text. Malloy parses routes, including
`#"` descriptions and application routes such as `#(research)`. The upstream
stable model and source metadata remain available alongside this projection.
