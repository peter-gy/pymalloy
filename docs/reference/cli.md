# CLI

`pymalloy` runs, checks, formats, and exports local
[Malloy](https://docs.malloydata.dev/documentation/) source files. Install
`pymalloy[headless]` for compiler and native execution commands.
[DuckDB](https://duckdb.org/docs/stable/) executes their SQL.

```sh
pymalloy run examples/orders.malloy --query orders.by_region --data-root examples
```

The command writes a JSON array of regional totals and order counts to stdout.
The example file contains North revenue `105` and South revenue `95`.

## Global options and exit codes

`pymalloy [-h | --help] [--version] {run,check,format,export} ...`

`-h` and `--help` show help and exit successfully at the root and on every
subcommand. `--version` prints `pymalloy VERSION` and exits successfully.
A subcommand is required for work.

| Code | Meaning                                                                      |
| ---- | ---------------------------------------------------------------------------- |
| `0`  | Success, valid check, already-formatted check, version, or help              |
| `1`  | Compiler/runtime/I/O failure, invalid checked source, or formatting required |
| `2`  | Argument parsing or export output-path validation failure                    |

Command failures go to stderr. `run` emits JSON on stdout. `check --json` emits a
structured report on stdout. Plain `check` diagnostics and its OK/FAILED summary
use stderr. `format` emits source on stdout. `export` reports its output path and
query count on stderr.

## Shared native options

These flags are accepted by `run`, `check`, and `export`.

| Flag                     | Default and behavior                                                                                                       |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------- |
| `--data-root PATH`       | For `run` and `check`, the connection-opening directory. For `export`, the model's parent. Configures relative data lookup |
| `--database PATH`        | An in-memory engine when omitted. A supplied existing database opens read-only                                             |
| `--timeout SECONDS`      | `120`, a positive finite operation budget                                                                                  |
| `--extension NAME`       | Empty list. Repeat to install and load native extensions before compilation                                                |
| `--connection-name NAME` | `duckdb`, the Malloy name served by the engine                                                                             |

Imports resolve from the source file's URL, separately from the data root.
DuckDB checks the process directory before its configured data search path.
Extension installation can download from DuckDB's repository and needs network
access. `check --syntax-only` uses the parser with a fixed 30-second tooling
budget and opens no database. Its native configuration flags, including
`--timeout`, are accepted but do not configure that parse operation.

## run

`pymalloy run PATH [-q NAME] [--givens JSON] [native options]`

| Argument or flag          | Contract                                                                                                         |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `PATH`                    | Required local model or notebook-document source                                                                 |
| `-q NAME`, `--query NAME` | One named query, `source.view`, `run:N`, or `sql:N`. Omitted selects the last run or sole query. Ambiguity fails |
| `--givens JSON`           | Parameter bindings as a JSON object. Omitted uses declared defaults                                              |

The timeout covers opening, compilation, SQL preparation, and execution.
The output is one JSON array of row objects. Integers remain exact JSON integers.
Decimals and temporal scalars become strings. Other non-JSON scalars use their
Python string form. Nested arrays and records retain their shape. Non-finite
numbers fail JSON encoding. Consumers using JavaScript numbers must choose an
integer-safe JSON parser for integers exceeding its safe range.

`--givens` accepts finite JSON values with exact integer parsing. A non-object or
non-finite number is an argument error. Malloy checks binding names and types.

## check

`pymalloy check PATH [--syntax-only] [--json] [native options]`

| Argument or flag | Contract                                                                                      |
| ---------------- | --------------------------------------------------------------------------------------------- |
| `PATH`           | Required local source file, read with its authored line endings                               |
| `--syntax-only`  | Parse syntax and report symbols, imports, and tables. Imported source and data are not loaded |
| `--json`         | Print the typed report using Python field names                                               |

Semantic checking resolves names, imports, types, and schemas. The report includes
query descriptors and native model metadata. Syntax-only success establishes
parser acceptance. It can accept an unresolved source name.

```sh
pymalloy check examples/orders.malloy --data-root examples --json
pymalloy check examples/orders.malloy --syntax-only
```

Both commands exit `0` for the bundled example. Diagnostic reports use zero-based
coordinates. Printed locations use one-based line and column numbers.

## format

`pymalloy format PATH [--check]`

| Argument or flag | Contract                                                    |
| ---------------- | ----------------------------------------------------------- |
| `PATH`           | Required local source file                                  |
| `--check`        | Exit `1` if formatted bytes would differ. Keep stdout empty |

Formatting uses Malloy's experimental formatter and a fixed 30-second compiler
budget. The command preserves the input file and its authored line endings for
comparison. Write formatted stdout to a separate file before replacing source.
Invalid source exits `1` with compiler diagnostics.

```sh
pymalloy format examples/orders.malloy > /tmp/formatted-orders.malloy
pymalloy format /tmp/formatted-orders.malloy --check
```

The second command exits `0`.

## export

`pymalloy export MODEL --format {marimo,jupyter} -o OUTPUT [options]`

| Argument or flag                          | Default and behavior                                                                              |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `MODEL`                                   | Required local `.malloy`, `.malloynb`, or `.malloysql` file                                       |
| `--format {marimo,jupyter}`               | Required notebook format                                                                          |
| `-o PATH`, `--output PATH`                | Required `.py` for marimo or `.ipynb` for Jupyter. Must differ from model and database            |
| `--profile {precompiled,headless,widget}` | `precompiled`. Chooses embedded SQL, native PyMalloy, or browser widgets                          |
| `-q NAME`, `--query NAME`                 | Repeat to choose queries in order. Accepts names, `source.view`, `run:N`, and `sql:N`             |
| `--all`                                   | Select every query. Mutually exclusive with `--query`                                             |
| `--files JSON`                            | `{}`, mapping source aliases to local file paths for SQL reader inputs                            |
| `--remote-file URL`                       | Empty list. Repeat for HTTP(S) inputs inside SQL readers                                          |
| `--title TEXT`                            | Title-cased filename stem with underscores changed to spaces                                      |
| `--givens JSON`                           | Parameter bindings as a finite JSON object                                                        |
| Native options                            | `--data-root`, `--database`, `--timeout`, `--extension`, `--connection-name` as specified earlier |

Compilation and rendering finish before an existing output is replaced. Parent
output directories are created. Default query selection follows document order
for notebook documents. Plain models select runs, then named queries, then views.

```sh
pymalloy export examples/orders.malloy --format marimo --all -o /tmp/orders.py
pymalloy export examples/sales.malloynb --format jupyter --profile widget -o /tmp/sales.ipynb
```

[marimo](https://docs.marimo.io/) is a reactive Python notebook editor.
[Jupyter](https://docs.jupyter.org/) hosts notebook kernel cells. Install the
selected host and the generated notebook's dependencies to execute the file.
Rendering writes text before any notebook execution occurs.

Native export profiles restrict file access to declared inputs and COPY outputs.
Declare SQL readers through `--files` or `--remote-file`. Remote inputs require
network access during preparation and execution and remain live dependencies.
Widget profiles reject native database state, COPY, and native extension options.
See [notebook export](../guide/export.md) for file and browser requirements.
