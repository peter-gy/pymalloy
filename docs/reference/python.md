# Python API

Import `pymalloy as pm`. The root namespace exposes constructors, native runtime
owners, language tools, the widget, and the common error base.

```python
import pymalloy as pm

with pm.connect() as con:
    result = con.model("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }").query().run()
print(result.to_pylist())
```

The result is `[{'answer': 42}]`. Native execution requires `pymalloy[headless]`.
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

Construction, widgets, and installed agent guidance use base dependencies.
`pm.data` requires [PyArrow](https://arrow.apache.org/docs/python/), the Python
library for columnar data. Parsing, file reading through `read_model`, formatting,
checks, validation, native execution, and export preparation require the
headless extra. Install [Polars](https://docs.pola.rs/), a dataframe library,
directly for `Result.to_polars()`.

## Qualified modules

| Module                                | Additional public values                                                    |
| ------------------------------------- | --------------------------------------------------------------------------- |
| `pymalloy.authoring`                  | `Input`, source/view/draft constructors                                     |
| `pymalloy.expressions`                | `call`, `number`, scalar constructors                                       |
| `pymalloy.analysis`                   | [Reports, schemas, locations, and `to_dict`](analysis.md)                   |
| `pymalloy.errors`                     | [Specific exceptions and `ExecutionContext`](runtime.md#errors)             |
| `pymalloy.validation`                 | [`DocumentationPolicy`, `Validation`, `DataCheck`](authoring.md#validation) |
| `pymalloy.result`                     | `Result`, `Column`                                                          |
| `pymalloy.widget`, `pymalloy.browser` | [`MalloyWidget`, `Bundle`, `Runtime`](widget.md)                            |
| `pymalloy.export`                     | [Notebook preparation, renderers, and bundles](export.md)                   |
| `pymalloy.agent`                      | `agent_plugin()`, `agent_skill()` for installed guidance                    |

Function and method docstrings provide parameter details and runnable examples.
Use `help(pm.connect)`, `help(pm.Source)`, or your editor's API lookup.
