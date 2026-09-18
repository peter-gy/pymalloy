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

After active cancellation, create a new Python model or TypeScript session.
Completed results remain readable.

After a schema change, compile a new model. After changing a widget mapping,
assign it back to `files` or `givens` to publish a new revision.
