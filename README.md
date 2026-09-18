# PyMalloy

Use [Malloy](https://www.malloydata.dev/) to define an analysis once, explore it
in a notebook, and run it from Python. [DuckDB](https://duckdb.org/) executes the queries.

```sh
pip install pymalloy
```

Display a query in a Jupyter or marimo notebook:

```python
from pymalloy import MalloyWidget

query = MalloyWidget("""
    run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }
""")
query
```

The widget shows `42`. It runs in the browser and downloads DuckDB WebAssembly
on first use.

- [Explore files and read widget results](https://peter-gy.github.io/pymalloy/guide/widget)
- [Query files, dataframes, and databases from Python](https://peter-gy.github.io/pymalloy/guide/server-python)
- [Export marimo or Jupyter notebooks](https://peter-gy.github.io/pymalloy/guide/export)
- [Author and verify models](https://peter-gy.github.io/pymalloy/guide/authoring)
- [Check and inspect source](https://peter-gy.github.io/pymalloy/guide/language-tools)
- [Use the JavaScript APIs](https://peter-gy.github.io/pymalloy/reference/browser)

[Documentation](https://peter-gy.github.io/pymalloy/guide/overview) ·
[Examples](examples) · [Contributing](development_docs/README.md)

Agents can import `pymalloy.agent` and start with `help(pymalloy.agent)`.
