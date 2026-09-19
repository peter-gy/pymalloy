# Troubleshooting

For `CompilationError`, inspect `error.diagnostics` or run `pymalloy check PATH
--json`. Source positions are zero-based in reports and one-based in printed
CLI locations.

If a file is missing, check the connection's `file_search_path`, the process
working directory, and the model's import URL separately. Borrowed connections
retain their caller's settings. Use absolute paths to disambiguate duplicate
filenames.

For widget errors, inspect `widget.state["error"]` and `diagnostics`. Remote files
and WebAssembly assets require reachable URLs and CORS permission. Declare SQL
reader files explicitly when exporting widgets.

A SQL timeout interrupts the statement and leaves a healthy model or TypeScript
session available for another query. A timeout while waiting for queued work
leaves the active operation running. Compiler failure or worker death requires a
new model or session. Completed results remain readable. See the
[error reference](../reference/headless.md#result-and-errors) for exception types.

After a schema change, compile a new model. Widget input mappings are read-only.
Assign a replacement, such as `widget.givens = {**widget.givens, "minimum": 20}`,
to publish a new revision for a model that declares `minimum`.
