# Check and inspect Malloy source

Check source, inspect models, and compile SQL with a native `Session`.
These tools require `pymalloy[server]`.

```python
from pymalloy.server import Session

source = "run: duckdb.sql('SELECT 42 AS answer') -> { select: missing }"

with Session() as session:
    report = session.check(source, path="analysis.malloy")
    assert not report.ok
    diagnostic = report.diagnostics[0]
    print(diagnostic.code, diagnostic.severity)
    # field-not-found error

    repaired = source.replace("select: missing", "select: answer")
    assert session.check(repaired, path="analysis.malloy").ok
    model = session.model(repaired)
    sql = model.sql()
    result = model.run()
    assert result.item() == 42
```

`check()` reports language errors. `path` identifies the source and resolves
imports. Semantic checks access data schemas, so use trusted models and provide
their files, credentials, and extensions. `syntax_only=True` skips imports and
schema discovery.

In `.malloynb` and `.malloysql`, checks cover Malloy, including embedded expressions.
Standalone SQL still needs DuckDB validation. Use `model.sql(query="sql:1")` to
inspect a cell's SQL with Malloy expressions compiled and data paths resolved.

## Read diagnostic locations

`CheckResult.to_dict()` returns a detached report that can be serialized as JSON:

```python
import json
from pymalloy.server import Session

with Session() as session:
    report = session.check("run: missing_source", path="analysis.malloy")

payload = json.dumps(report.to_dict())
assert json.loads(payload)["ok"] is False
```

Reports include diagnostics, symbols, table paths, imports, query selectors,
source URL, and compiler version. Semantic checks add schemas in
`report.native.sources` and, when query schemas are available, `report.native.model`.
Diagnostic replacements apply to the reported source range.

The `missing` field produces this diagnostic when the source path is
`/workspace/analysis.malloy`:

```json
{
  "code": "field-not-found",
  "severity": "error",
  "message": "'missing' is not defined",
  "location": {
    "url": "file:///workspace/analysis.malloy",
    "range": {
      "start": { "line": 0, "character": 52 },
      "end": { "line": 0, "character": 59 }
    }
  },
  "replacement": null,
  "data": null,
  "error_tag": null
}
```

Positions use zero-based lines and Unicode code points. An emoji occupies one
character position. The range end is exclusive, matching Python string slicing.
Preserve the diagnostic's URL when editing imported source.

For a file, run:

```sh
pymalloy check analysis.malloy --json
pymalloy check analysis.malloy --syntax-only --json
```

Checks exit with `0` for success (including warnings), or `1` for errors.
Setup and file errors go to standard error.

## Ask for completions and context

Pass `Position` to obtain native completion text and help at a source location:

```python
from pymalloy.analysis import Position
from pymalloy.server import Session

source = """source: numbers is duckdb.table('numbers.csv')
run: numbers -> {
  group_by: value

}"""

with Session() as session:
    choices = session.check(source, syntax_only=True, position=Position(3, 2))
    context = session.check(source, syntax_only=True, position=Position(2, 3))

assert {"type": "query_property", "text": "group_by: "} in choices.completions
assert context.help == {"type": "query_property", "token": "group_by:"}
```

## Inspect a retained model

`model.inspect()` returns JSON-serializable metadata, givens, dependencies,
selectors, and diagnostics. Supply a position to inspect references and imports,
and `url` to select an imported document. Reference IDs may change between
compilations, so compare schema fields and diagnostics instead.

Required givens can leave `native.model` as `None` while `native.sources` remains
available. `inspection["givens"]` lists each parameter's `name`, `type`, `required`,
and `default_text`. Pass values to `model.sql(givens=...)` or `model.run(givens=...)`.

`model.sql()` accepts the same query inputs as `model.run()` and returns SQL with
resolved data paths, without executing it. Review `COPY` statements before
execution: they write files.

Report fields match across Python and JavaScript. `native` uses Malloy's schema
format. Other records are defined in the [analysis reference](/reference/analysis).

## Format source

Malloy's upstream formatter is experimental. Review its output before applying
it to authored files:

```sh
pymalloy format analysis.malloy > formatted.malloy
pymalloy format analysis.malloy --check
```

Formatting writes to standard output and preserves the input file. `--check`
exits with `1` if formatting would change it. Malformed source exits with `1`
and diagnostics on standard error.

In Python, `session.format(source)` returns text or raises `CompilationError`
with diagnostics. See the [Python API](/reference/server) and [CLI reference](/reference/cli).
