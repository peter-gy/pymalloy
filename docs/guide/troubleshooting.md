# Troubleshooting

Import domain exceptions from `pymalloy.errors`. Use the symptom to choose the
next check:

| Symptom                                    | Cause to inspect                                           | Next action                                                                               |
| ------------------------------------------ | ---------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `CompilationError`                         | Invalid source, unresolved name, or missing schema         | Read `error.diagnostics` or run `pymalloy check PATH --json`                              |
| `CompilationError` caused by `SchemaError` | The engine failed a schema probe                           | Inspect `error.__cause__.sql` and its original cause, then check the connection and files |
| `ExecutionError`                           | SQL compiled but the engine rejected execution             | Retain `error.context` and `error.__cause__`, then replay with the same data and settings |
| `ClosedError`                              | A connection or model was closed                           | Create a connection or compile another model                                              |
| `CompilerError`                            | Embedded compiler or boundary validation failed            | Retain diagnostics and compile another model                                              |
| `ValidationError`                          | A check failed or strict warnings were rejected            | Read `error.report.checks` and its counterexamples before revising the definition         |
| `TimeoutError` during SQL                  | The statement exceeded its budget                          | Reduce the query or increase `timeout`, then reuse a healthy model                        |
| `TimeoutError` during compiler work        | An active compiler request exceeded its budget             | Compile another model                                                                     |
| Missing or wrong file                      | Import URL, process directory, and data search path differ | Inspect each separately and use absolute paths to disambiguate                            |
| Widget fails to load                       | Packaged assets or browser worker policy                   | Inspect `widget.bundle_status` and browser errors                                         |
| Widget query fails                         | Source diagnostics, data URL, or network permission        | Inspect `widget.state["error"]` and `diagnostics`                                         |
| Native API requested in Pyodide            | A synchronous native entry point was selected              | Use `pymalloy.browser.connect()` and await browser operations                             |

## Diagnose file access

[DuckDB](https://duckdb.org/docs/stable/), the SQL engine, checks the current
process directory before `file_search_path`. [Malloy](https://docs.malloydata.dev/)
imports resolve from the model URL. A borrowed connection keeps the caller's
settings. See [data access](data.md).

Remote files and [WebAssembly runtime assets](https://duckdb.org/docs/stable/clients/wasm/overview.html)
need reachable URLs and cross-origin resource sharing permission.
Declare SQL-reader files explicitly when exporting notebooks.

## Recover runtime and notebook state

A SQL timeout can abort an explicit borrowed transaction. The connection owner
must roll it back. A queued timeout leaves the active operation running.
Compiler failure closes the affected model. Browser worker death requires
another session. Completed results remain readable.

After changing source or schema, compile another model. Replace widget mappings,
such as `widget.files = {**widget.files, "orders.csv": contents}`, to publish a
revision. See [runtime errors](../reference/runtime.md#errors).

After a package upgrade or class edits in an editable install, save the notebook
and restart its kernel. Automatic module reload can mix expression class versions.
An error asking for `col()`, `lit()`, or `Expr.raw()` on a value created with
`pm.col()` can indicate this mismatch. Rerunning an import can retain existing
class references in other cells.
