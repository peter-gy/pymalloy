# PyMalloy

Use [Malloy](https://www.malloydata.dev/) to define an analysis once, explore it
in a notebook, and run it from Python. [DuckDB](https://duckdb.org/) executes the queries.

```sh
pip install pymalloy
```

```python
from pymalloy import MalloyWidget

query = MalloyWidget("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }")
query
```

Display the widget in a marimo or Jupyter notebook. It shows one row with
`answer` equal to `42`. First use downloads DuckDB's versioned WebAssembly runtime.
Read `query.state` for the latest asynchronous result, or observe its state changes.

- [Explore with the widget](https://peter-gy.github.io/pymalloy/guide/getting-started).
- [Run server-side Python queries](https://peter-gy.github.io/pymalloy/guide/server-python)
  with `pymalloy[server,dataframes]`.
- [Author and verify models](https://peter-gy.github.io/pymalloy/guide/authoring)
  with immutable drafts, compiler checks, and named data assertions.
- [Check and inspect source](https://peter-gy.github.io/pymalloy/guide/language-tools)
  from Python or the command line.
- [Export marimo and Jupyter notebooks](https://peter-gy.github.io/pymalloy/guide/export).

[Documentation](https://peter-gy.github.io/pymalloy/guide/overview) ·
[API reference](https://peter-gy.github.io/pymalloy/reference/python)
