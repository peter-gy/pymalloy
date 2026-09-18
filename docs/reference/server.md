# Native Python API

`pymalloy.server` compiles Malloy and queries native DuckDB. Install `pymalloy[server]` first.

```python
from pymalloy.server import Session

with Session() as session:
    result = session.run("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }")

assert result.item() == 42
```

Queries return materialized [Polars](https://docs.pola.rs/) dataframes that remain
available after closure. See [Data and connections](/guide/data) for data setup.

## `Session`

```text
Session(*, data_root=None, database=None, connection=None, read_only=False, timeout=120)
```

Create an owned [DuckDB](https://duckdb.org/docs/stable/) connection or borrow one.
Owned connections open during construction. The compiler starts when an operation needs it.

| Argument     | Behavior                                                                                                  |
| ------------ | --------------------------------------------------------------------------------------------------------- |
| `data_root`  | Directory for relative data paths. Defaults to the loaded file's parent or inline model's base directory. |
| `database`   | Database file to open. Defaults to an in-memory database.                                                 |
| `connection` | Existing DuckDB connection to borrow. Pass it independently of `database` and `read_only`.                |
| `read_only`  | Open the database read-only. Defaults to `False`.                                                         |
| `timeout`    | Positive, finite operation budget in seconds. Defaults to `120`.                                          |

`data_root` and `database` accept strings or `pathlib.Path` objects. `data_root`
must name an existing directory. Invalid options raise `ValueError`, and database
opening failures retain DuckDB's exception types.

`session.connection` is a read-only property exposing the native connection.
Use it to register data and configure settings. Changing connections requires a new session.
Owned connections start in UTC. Use a context manager or `session.close()` for
cleanup. `session.closed` reports closure.

### `session.model(source, *, base_dir=None)`

Load inline source, resolve local imports, and discover schemas. Returns a `Model`.
Imports use `base_dir`, defaulting to `data_root` or the working directory.
Data files use `data_root` when supplied, otherwise `base_dir`.

### `session.load(path)`

Load a local `.malloy`, `.malloynb`, or `.malloysql` file and return a `Model`.
`path` accepts a string or `pathlib.Path`. Imports resolve beside the file.
Loading discovers schemas within the session timeout. Missing files raise `FileNotFoundError`.

### `session.load_source(source)`

Load a captured [`ModelSource`](/reference/python#modelsource) and return a `Model`.
Imports use its `imports` mapping. Missing imports raise `CompilationError`.
The session discovers schemas and resolves relative data paths from `data_root`
or the working directory. The root URL identifies source locations and imports,
independently of the data directory.

```python
from pymalloy import ModelSource
from pymalloy.server import Session

source = ModelSource(
    url="memory://example/answer.malloy",
    text="run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }",
)
with Session() as session:
    model = session.load_source(source)
    assert model.run().item() == 42
```

### `session.run(source, *, query=None, givens=None, timeout=None)`

Load inline source, execute a query, and release its temporary model. Returns a
Polars dataframe. `query` selects a query defined in the supplied source.
`givens` supplies typed values for this call. `timeout` overrides the session's
operation budget.

### `session.check(source, *, path=None, syntax_only=False, position=None, timeout=None)`

Return a [`CheckResult`](/reference/analysis#checkresult) with diagnostics and source
metadata. Semantic checking resolves imports and schemas, including embedded
Malloy in `.malloynb` and `.malloysql`. Standalone SQL requires DuckDB validation
or execution. Checks do not execute result queries. Use trusted models with configured data access.

| Argument      | Behavior                                                                                                                                                 |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `source`      | Malloy source text.                                                                                                                                      |
| `path`        | File identity for diagnostics and relative imports. Defaults to `inline.malloy` under the data root or working directory. The draft file may be unsaved. |
| `syntax_only` | Parse source before resolving imports or data. Defaults to `False`.                                                                                      |
| `position`    | Optional `Position` for native completion text and contextual help.                                                                                      |
| `timeout`     | Override the session operation budget in seconds.                                                                                                        |

Language errors make `result.ok` false. Warnings keep it true. The parser returns
recoverable symbols, table paths, and import locations. Semantic checks add
`native` schemas and query selectors. Unbound required givens can leave
`result.native.model` as `None`. Use [`Position`](/reference/analysis#position) for
`position`. Imports must be local files. Invalid argument types raise `TypeError`.

### `session.check_file(path, *, syntax_only=False, position=None, timeout=None)`

Read a local `.malloy`, `.malloynb`, or `.malloysql` file as UTF-8 and call `check()`
with its identity. File access failures raise `OSError`. Other arguments match `check()`.

### `session.format(source, *, timeout=None)`

Return Malloy text formatted by its experimental upstream formatter. It parses
source without writing files, discovering schemas, or executing SQL. Malformed
source raises `CompilationError` with syntax diagnostics. Review changes before
writing files. Accepts `.malloy` text, not complete `.malloynb` or `.malloysql` documents.

### `session.close()`

Release the compiler bridge and owned connection. Models from this session
become invalid. Borrowed connections remain caller-owned. Repeated calls are safe.

## `Model`

Get a model from `session.model()`, `session.load()`, or `session.load_source()`.

### `model.queries`

A tuple of selectors: named queries, exported `source.view` names, and one-based
`run:N` and `sql:N` cells. SQL cells belong to `.malloynb` or `.malloysql` documents.

### `model.run(source=None, *, query=None, givens=None, timeout=None)`

Execute a query against the retained model and return a Polars dataframe.

- `source` supplies full Malloy query source, including `run:`.
- `query` selects an available query. Pass `source` or `query` for a call.
- `givens` supplies typed overrides for one execution.
- `timeout` overrides the session's operation budget in seconds.

With neither `source` nor `query`, execute the final run or single available
query. Multiple choices require `query=`. Document `COPY` cells write their
destination and return an empty dataframe.

Row changes are visible on the next query. Reload a model after changing schemas
or imported definitions. See [Givens](/guide/givens) for accepted value types.
Results materialize before returning. Size queries to fit Python's available memory.

### `model.inspect(*, position=None, url=None, timeout=None)`

Return a JSON-serializable dictionary from the retained model:

| Field                              | Content                                                                                                         |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `native.model`                     | Malloy model information, including exported entries, field schemas, anonymous queries, and native annotations. |
| `native.sources`                   | Malloy source metadata available before required givens are supplied.                                           |
| `queries`                          | Available query selectors.                                                                                      |
| `givens`                           | Given names, types, required flags, default text, locations, and annotations.                                   |
| `annotations`, `model_annotations` | Annotation records, preserving their routes and source locations.                                               |
| `dependencies`                     | Imported source URLs.                                                                                           |
| `imports`                          | Import targets and locations.                                                                                   |
| `diagnostics`                      | Native compiler diagnostic records.                                                                             |

Required givens can leave `native["model"]` as `None`. Inspect `native["sources"]`
and `givens`, then supply values to `model.sql()` or `model.run()`.

With `position`, the result also includes `reference` and `import`. A reference
contains `text`, `kind`, `location`, `definition_location`, `definition_type`,
`default_text`, and `annotations`. Either lookup can return `None` when the
position has no match.

`url` selects an imported document and requires `position`. It defaults to the
model's root document. Positions use zero-based lines and Unicode code points.
`timeout` overrides the session's operation budget.

Records are dictionaries and lists:

- Annotations contain `route`, `text`, `content`, and `location`. In `#(docs)`,
  the route is `docs`. `text` includes the prefix, and `content` is its payload.
- Imports contain `url` and `location`.
- Givens contain `name`, string `type`, boolean `required`, `default_text`,
  `location`, and `annotations`. `default_text` is the authored expression or
  `None` when a value is required.

`native` preserves the bundled compiler's schema. Other fields describe PyMalloy
queries, givens, and source. Native annotation IDs may change on recompilation.

### `model.sql(source=None, *, query=None, givens=None, timeout=None)`

Return DuckDB SQL with resolved data paths. Arguments match `model.run()`.
The caller executes SQL, including `COPY` writes. Source loading may already have
read data for schemas. Diagnostics for query source use
`memory://pymalloy/query.malloy` and positions in that string. Imported definitions
retain their URLs.

### `model.close()`

Release the retained model. Repeated calls are safe. Models also support context
managers.

## Errors

```python
from pymalloy.server import CompilationError, SessionError
```

`CompilationError` reports syntax, schema, selection, and binding failures. Its
`diagnostics` tuple contains available compiler diagnostics. Execution failures
retain DuckDB or Polars exception types. These errors leave the session available.
Follow DuckDB's rollback requirements for caller-owned transactions.

`SessionError` reports a closed model, closed session, or failed compiler process.
A failed compiler process closes the session.

Invalid Python arguments raise `TypeError` or `ValueError` before compilation.
Passing both `source` and `query` to `model.run()` or `model.sql()` raises `ValueError`.
Root file errors in `check_file()` retain `OSError`. Compiler-reported import
failures become `CompilationError` or check diagnostics.

## Timeouts and concurrency

Timeouts cover bridge work and SQL execution. Calls on one session are serialized.
A timeout waiting for another call leaves that call running. A timeout or
interruption during an active operation closes the session and invalidates its
models. A borrowed connection remains caller-owned.
`KeyboardInterrupt` and `SystemExit` during bridge work also close the session.
Coordinate direct calls to `session.connection` with session operations, because
the session serializes its own calls. Use separate sessions for concurrent queries.

See [Analysis records](/reference/analysis) for diagnostics and positions, and
[Check and inspect source](/guide/language-tools) for checking and repair examples.
