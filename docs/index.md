---
layout: home
hero:
  name: PyMalloy
  text: Malloy in Python notebooks.
  tagline: Define models in Malloy. Explore them in a notebook, run them from Python,
    and share executable analyses.
  actions:
    - theme: brand
      text: Run your first query
      link: /guide/getting-started
    - theme: alt
      text: Choose where to run
      link: /guide/overview
features:
  - title: Query in the browser
    details: Explore files and remote data with an interactive Malloy widget powered by DuckDB.
  - title: Read results in Python
    details: Receive rows, columns, SQL, and errors, with nested values and exact integers preserved.
  - title: Choose your runtime
    details: Run server-side Python or Node sessions, or export an executable marimo or Jupyter notebook.
---

## Display a query

Install `pymalloy`, then run a [Malloy](https://www.malloydata.dev/) query in
Jupyter or marimo:

```sh
pip install pymalloy
```

```python
from pymalloy import MalloyWidget

query = MalloyWidget("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }")
query
```

The widget shows `42`. First use downloads DuckDB WebAssembly into the browser.
Follow [your first widget](/guide/getting-started) to supply data and read results
in Python, or [choose another runtime](/guide/overview).
