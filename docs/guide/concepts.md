# Models, queries, and execution

A model snapshots Malloy source, imports, and schemas. A query selects an authored
run, named query, source view, SQL cell, or ad hoc Malloy text.

```text
model(source) → query(name) → sql() / run() → Result
```

Python's `pm.run(source)` executes once and releases its resources before
returning. `pm.model(source)` retains a model for repeated execution. Each model
owns a Deno compiler process and an owned or borrowed DuckDB connection.

Malloy generates SQL. DuckDB executes that SQL against current data. The browser
uses DuckDB WebAssembly, while Node and Python use native DuckDB connections.
Browser and Node callers create a `Session` to own their asynchronous runtime.

`sql()` prepares a query without executing it. `run()` returns SQL, columns, and
materialized rows. Python results also offer `.arrow()` and `.polars()` with the
`dataframes` extra.

Python operations serialize within each model. TypeScript operations serialize
within each session. Cancelling queued work rejects that call. Cancelling active
work interrupts execution and closes its runtime. Completed results remain usable.
