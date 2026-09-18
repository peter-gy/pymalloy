# CLI

`pymalloy` checks and formats source and exports notebooks:

```sh
pip install "pymalloy[server]"
pymalloy check analysis.malloy --json
```

Use an existing model, such as the [export guide's example](/guide/export).
Command help is available with the base package.

## `pymalloy check`

```text
pymalloy check PATH [--syntax-only] [--json] [--data-root PATH] [--database PATH]
```

Check a local `.malloy`, `.malloynb`, or `.malloysql` file. Document checks include
embedded Malloy. Standalone SQL cells require separate DuckDB validation or
execution. Semantic checks resolve imports and schemas, requiring data access
and credentials. `--syntax-only` parses before accessing imports or data.
`--data-root` sets the directory for relative data paths. `--database` opens an
existing DuckDB database read-only.

`--json` writes one [check report](/reference/analysis#checkresult) to standard
output. Human-readable diagnostics and status use standard error. Human locations
use one-based line and character numbers. JSON locations use zero-based lines and
Unicode code points.

Exit status is `0` for success, including warnings, `1` for language, setup, or
file errors, and `2` for invalid arguments. Setup and file errors use standard
error. Source files are preserved.

## `pymalloy format`

```text
pymalloy format PATH [--check]
```

Write a local `.malloy` file's formatted source to standard output using Malloy's
experimental formatter. `--check` returns `1` if formatting would change the
file, or `0` if it already matches. The input file is preserved.

Malformed source and file errors return `1` with diagnostics on standard error.
Invalid arguments return `2`. Review the formatter's output before applying it:

```sh
pymalloy format analysis.malloy > formatted.malloy
```

## `pymalloy export`

```text
pymalloy export MODEL --format marimo|jupyter --output PATH [--profile precompiled|native|widget]
```

`MODEL` is a local `.malloy`, `.malloynb`, or `.malloysql` file.

| Flag                | Behavior                                                                                                                           |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `--format marimo`   | Render a marimo Python notebook.                                                                                                   |
| `--format jupyter`  | Render a Jupyter notebook.                                                                                                         |
| `--output PATH`     | Write the rendered notebook at this location.                                                                                      |
| `--profile PROFILE` | `precompiled` (default) for PyMalloy-free SQL execution, `native` for a Python model, or `widget` for interactive browser widgets. |
| `--query SELECTOR`  | Select a query. Repeat the flag for several queries.                                                                               |
| `--query '*'`       | Select every available query. Quote `*` to prevent shell expansion.                                                                |
| `--data-root PATH`  | Resolve relative data paths under this directory. Defaults to the model's directory.                                               |
| `--database PATH`   | Discover schemas from an existing DuckDB database and record that database in the export.                                          |
| `--title TEXT`      | Set the generated document title.                                                                                                  |
| `--givens JSON`     | Supply a JSON object of given values to every selected query.                                                                      |
| `--help`            | Show command usage and options.                                                                                                    |

`-o` abbreviates `--output`, and `-q` abbreviates `--query`. Selectors include
named queries, `source.view`, `run:N`, and `sql:N`, with numbering starting at 1.
With no selectors, `.malloy` files choose runs, otherwise named queries,
otherwise exported source views. Malloy documents preserve authored Markdown
and executable order. Explicit selectors emit query cells in selector order
and omit authored Markdown. See [Query selection](/reference/export#query-selection).

Install `pymalloy[server,marimo]` for marimo exports or `pymalloy[server,jupyter]`
for Jupyter exports.

Use `.py` for marimo or `.ipynb` for Jupyter. The output path must differ from the
source model and database. Parent directories are created as needed. Existing
output is replaced after successful compilation and rendering.

Exit status is `0` on success, with the output path and query count on standard
error. Compilation, dependency, and file errors return `1`. Invalid arguments return `2`.

## Export selected views

```sh
pymalloy export analysis.malloy --format jupyter \
  --query orders.by_region --query orders.region_detail --output /tmp/orders.ipynb
```

The generated notebook reads its files or database when it executes. Keep the
referenced data accessible. Document `COPY` cells write their destination when
the notebook runs in the native and precompiled profiles. Widget export rejects
databases, `COPY`, globs, computed file-reader arguments, and non-HTTP URL schemes.
See [Export notebooks](/guide/export) for data requirements.

## Export with given values

Using the [parameterized model](/guide/export#set-given-values):

```sh
pymalloy export filtered.malloy --format jupyter \
  --givens '{"minimum": 20}' --output filtered.ipynb
```

The object may contain strings, booleans, finite numbers, `null`, arrays, and
nested objects. Quote the JSON to preserve it in the shell. Malformed JSON or a
top-level value other than an object returns exit status `2`. The default
`precompiled` profile captures supplied values in SQL. Add `--profile native` or `--profile widget`
to keep an editable `givens` mapping and the complete model in the notebook.
See [Choose a profile](/guide/export#choose-a-profile) for runtime dependencies
and model editing.
