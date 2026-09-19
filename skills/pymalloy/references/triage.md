# Investigate a failing query

Identify the stage before changing the model:

| Stage               | Evidence and next action                                                                                                                                                             |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Python construction | `TypeError` or `ValueError` before compilation. Check constructor arguments and use `raw_expr` or native syntax for grammar outside the API.                                         |
| Malloy compilation  | `CompilationError.diagnostics` carries source locations. Inspect the installed compiler version, source and imports. Fix the original Malloy, then reconstruct Python if needed.     |
| Schema discovery    | A `CompilationError` caused by `SchemaError` retains the failing DESCRIBE SQL and original engine cause. Verify connection, file bindings and the source SQL.                        |
| Compiler service    | `CompilerError` identifies an internal compiler or transport failure. Retain the cause and restart the model. A deadline raises `TimeoutError`, not a model diagnostic.              |
| Engine execution    | `ExecutionError.context` retains the closed model, selected query or ad hoc text, parameters, SQL, compiler version and preview limit. `__cause__` is the original DuckDB exception. |
| Semantic validation | A failed data assertion retains a counterexample. Inspect grain, keys, population, denominator, time reference and join relationships rather than changing syntax to silence it.     |

This runnable example uses `pymalloy[headless]`:

```python
import duckdb
import pymalloy as pm

source = """source: values is duckdb.sql("SELECT 'invalid' AS value")
query: numeric is values -> { select: value is value::number }
"""
model = pm.model(source)
try:
    try:
        model.query("numeric").run()
    except pm.ExecutionError as error:
        context = error.context
        assert isinstance(error.__cause__, duckdb.ConversionException)
        assert context.query.name == "numeric"
        assert context.compiler_version
        assert context.sql
    else:
        raise AssertionError("Expected invalid numeric conversion")
finally:
    model.close()

# Replay after the original runtime has closed.
replay = pm.model(context.source, connection_name=context.connection_name)
try:
    try:
        replay.query(context.query.name).run(givens=context.givens)
    except pm.ExecutionError as repeated:
        assert repeated.context.sql == context.sql
finally:
    replay.close()
```

For an ad hoc query, replay `model.query(malloy=context.malloy)`. For a preview,
use the recorded `preview_limit`. The context retains model text, imports, and
managed input owners. Its `source` property contains text only. Supply the same
external data and connection settings when replaying that source. A context does
not capture a database transaction. `bundle(context.source, ...)` can materialize
its source graph with
explicit file bindings, while `context.sql` can be executed directly in DuckDB.

Inspect `model.inspect().givens` before passing parameters. An import-based
entrypoint can expose a different parameter scope. Remove a parameter only after
proving the selected query does not use it. Keep non-neutral defaults and time
references explicit in the production record.

When SQL fails after successful compilation, retain the original failure and
reduce the emitted Malloy plus its minimal schemas/data to a native reproducer.
Record compiler and DuckDB versions. Establish whether the same Malloy fails
outside the Python constructor path before attributing a bug upstream. Do not
patch generated SQL or add a permanent model workaround without checking its
meaning against the underlying data. Filing an external issue remains a separate
action requiring the user's authorization.
