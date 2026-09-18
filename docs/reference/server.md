# Server Python API

```python
import pymalloy as pm

result = pm.run("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }")
print(result.rows())
```

Install `pymalloy[server]` for server execution.

## model

`pm.model(source, *, url=None, data_root=None, database=None, connection=None,
tables=None, read_only=False, timeout=120, compiler_memory_mb=256)` compiles a
reusable `Model`.

- `source`: Malloy text, a `pathlib.Path`, or `ModelSource`. Strings always mean text.
- `url`: identity and import base for inline source.
- `data_root`: data search directory for an owned DuckDB connection.
- `database`: persistent DuckDB database path.
- `connection`: caller-owned DuckDB connection. Configure its settings yourself.
- `tables`: mapping of table names to Python data accepted by DuckDB registration.
- `read_only`: open a persistent database for reading.
- `timeout`: seconds available for construction and compilation, and the default for subsequent operations.
- `compiler_memory_mb`: compiler V8 heap limit in MiB, independent of DuckDB memory.

A model owns its compiler process and any connection it creates. Queries retain
the model. Resources are released when the model becomes unreachable.
`model.close()` releases them immediately and is idempotent. Borrowed connections
retain caller ownership, settings, and transactions.

## run

`pm.run(source, *, givens=None, **model_options)` runs the default query and
returns a materialized `Result`. It accepts the options of `pm.model` and closes
its temporary model before returning, including on failure. Its timeout covers
construction, compilation, and execution.

## Model and Query

`model.queries` contains `QueryDescriptor(name, kind, location)` records.
`model.query(name=None, *, malloy=None)` selects a query or an ad hoc Malloy query.
Omit both to select the final run or single available query.

`model.run(*, givens=None, timeout=None)` and `model.sql(*, givens=None,
timeout=None)` use that default query. Named selections expose the same methods
through `query.run(...)` and `query.sql(...)`.

`model.inspect(*, position=None, url=None, timeout=None)` returns `Inspection`.
`model.source(*, timeout=None)` returns `ModelSource`.
`model.document(*, queries=None, all=False, givens=None, timeout=None)` returns an
ordered tuple of typed `MarkdownCell` and `QueryCell` records. `queries=None` uses
the default selection. `queries=[]` selects no query cells. Authored Markdown or a
source inventory may remain.
Passing query names together with `all=True` is invalid.
`model.connection` exposes the DuckDB connection. Coordinate direct connection use
with model operations. `model.closed` reports whether execution is available.

## Language tools

`pm.check(source, *, path=None, syntax_only=False, position=None, data_root=None,
database=None, connection=None, read_only=False, timeout=120)` returns
`CheckReport` and releases its temporary resources.

`pm.format(source)` returns formatted source using the compiler.
`pm.parse(source, *, url)` returns a typed `ParseReport` with syntax metadata,
imports, and table references.
Neither function opens a DuckDB connection.

## Result and errors

`result.sql` is the executed SQL. `columns` is a tuple of `Column(name, type)`.
`rows()` returns detached dictionaries. `arrow()` and `polars()` convert values
with the `dataframes` extra. Results remain readable after model cleanup.

`CompilationError` carries compiler diagnostics. `ModelError` identifies a
closed model or failed compiler process. Invalid options raise `TypeError` or
`ValueError`. DuckDB errors retain their exception types. An active timeout
closes the model. A timeout waiting for its operation lock leaves active work
running. Heap exhaustion closes the model with `ModelError`.

Author models with [immutable drafts and source builders](authoring.md).
`pm.check` also accepts a `Path` or captured `ModelSource`, plus `url` and
registered Python `tables`. `Query.preview(limit=20)` bounds returned rows.
