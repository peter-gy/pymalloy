# Python API

Import `pymalloy as pm`. The root namespace exposes constructors, native runtime
owners, language tools, the widget, and the common error base.

```python
import pymalloy as pm

with pm.connect() as con:
    result = con.model("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }").query().run()
print(result.to_pylist())
```

The result is `[{'answer': 42}]`.
[Malloy](https://docs.malloydata.dev/) compiles the source and
[DuckDB](https://duckdb.org/docs/stable/), an embedded SQL database, runs it.

| Root names                                                         | Contract                                                     |
| ------------------------------------------------------------------ | ------------------------------------------------------------ |
| `table`, `sql`, `data`, `source`, `view`                           | [Source and View](authoring.md#source-and-view) construction |
| `col`, `lit`, `given`, `count`, `case`, `Expr`, `Sort`             | [Scalar expressions](authoring.md#scalar-expressions)        |
| `draft`, `read_model`, `Source`, `View`, `Draft`                   | [Draft composition and editing](authoring.md#draft)          |
| `connect`, `Connection`, `Model`, `Query`, `Result`, `ModelSource` | [Runtime and result contracts](runtime.md)                   |
| `parse`, `format`                                                  | [Language tools](runtime.md#language-tools)                  |
| `MalloyWidget`                                                     | [Widget inputs, state, and browser assets](widget.md)        |
| `PyMalloyError`                                                    | [Domain errors](runtime.md#errors)                           |

Native wheels include the compiler, DuckDB execution, widgets, and installed
agent guidance. PyMalloy installs [PyArrow](https://arrow.apache.org/docs/python/)
for data capture and columnar results. Install [Polars](https://docs.pola.rs/), a
dataframe library, separately for `Result.to_polars()`.

[Browser Python](browser-python.md) uses asynchronous `pymalloy.browser`
connections to run the same Malloy compiler with DuckDB WebAssembly. Install the
browser wheel in [Pyodide](https://pyodide.org/en/stable/), a browser-hosted Python
runtime. The [browser Python guide](../guide/browser-python.md) covers setup,
widgets, and queries.

## Qualified modules

| Module                 | Additional public values                                                                    |
| ---------------------- | ------------------------------------------------------------------------------------------- |
| `pymalloy.authoring`   | `Input`, source/view/draft constructors                                                     |
| `pymalloy.expressions` | `call`, `number`, scalar constructors                                                       |
| `pymalloy.analysis`    | [Reports, schemas, locations, and `to_dict`](analysis.md)                                   |
| `pymalloy.errors`      | [Specific exceptions and `ExecutionContext`](runtime.md#errors)                             |
| `pymalloy.validation`  | [`DocumentationPolicy`, `Validation`, `DataCheck`](authoring.md#validation)                 |
| `pymalloy.result`      | `Result`, `Column`                                                                          |
| `pymalloy.widget`      | [`MalloyWidget`](widget.md)                                                                 |
| `pymalloy.browser`     | [Asynchronous connections, models, queries, results, and runtime assets](browser-python.md) |
| `pymalloy.export`      | [Notebook preparation, renderers, and bundles](export.md)                                   |
| `pymalloy.agent`       | `agent_plugin()`, `agent_skill()` for installed guidance                                    |

Function and method docstrings provide parameter details and runnable examples.
Use `help(pm.connect)`, `help(pm.Source)`, or your editor's API lookup.
