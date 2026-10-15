# Investigate a failing query

Identify the stage before changing the definition:

| Stage               | Evidence and next action                                                                                                     |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Python construction | `TypeError` or `ValueError`. Check argument types and scoped names.                                                          |
| Compilation         | `pymalloy.errors.CompilationError.diagnostics` gives authored locations. Read source, imports, and compiler version.         |
| Schema discovery    | A `CompilationError` caused by `SchemaError` retains DESCRIBE SQL and its engine cause. Check connection and data access.    |
| Compiler service    | `CompilerError` closes the affected compiler. Create another model and retain the cause.                                     |
| Engine execution    | `ExecutionError.context` retains source, SQL, selection, bindings, compiler version, and preview limit. Inspect `__cause__`. |
| Validation          | A failed check retains a counterexample. Review grain, keys, population, denominator, time reference, and joins.             |

This example needs `pymalloy[headless]` and verifies detached failure replay:

```python
import duckdb
import pymalloy as pm
from pymalloy.errors import ExecutionError

source = """source: values is duckdb.sql("SELECT 'invalid' AS value")
query: numeric is values -> { select: value is value::number }
"""
with pm.connect() as con:
    model = con.model(source)
    try:
        model.query("numeric").run()
    except ExecutionError as error:
        context = error.context
        assert isinstance(error.__cause__, duckdb.ConversionException)
        assert context.query.name == "numeric"
    else:
        raise AssertionError("Expected invalid numeric conversion")

with pm.connect(name=context.connection_name) as con:
    replay = con.model(context.source)
    try:
        replay.query(context.query.name).run(givens=context.givens)
    except ExecutionError as repeated:
        assert repeated.context.sql == context.sql
    else:
        raise AssertionError("Expected the same conversion failure")
```

Replay ad hoc selections with `model.query(malloy=context.malloy)` and previews
with the recorded limit. `context.source` retains logical model text, imports,
and captured input owners. External files, database state, connection settings,
and transactions need the same caller setup. `bundle(context.source, ...)` can
materialize source and explicitly bound inputs.

A SQL timeout interrupts its statement and leaves a healthy model reusable.
An in-flight compiler timeout closes the model. Queued timeout leaves active
work running. An aborted borrowed transaction requires caller rollback.
Inspect `model.inspect().givens` before binding parameters.

Reduce unexpected SQL failures to the emitted Malloy and minimal input schemas
and values. Record compiler and DuckDB versions and compare with native Malloy
before assigning ownership of the bug. Keep the analytical meaning of any
workaround explicit. Filing an external issue requires user authorization.
