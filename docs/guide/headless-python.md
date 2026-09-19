# Run queries from Python

Install the native Python runtime:

```sh
pip install 'pymalloy[headless]'
```

```python
import pymalloy as pm

result = pm.run("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }")
print(result.rows())  # [{'answer': 42}]
table = result.arrow()
```

`pm.run` compiles and executes a query, then releases its compiler and connection
before returning. The result retains an Arrow table. `result.sql` contains the
executed SQL and `result.columns` describes the DuckDB columns. `arrow()` returns
the table, and `rows()` creates detached Python dictionaries. Install the optional
`polars` package to convert with `result.polars()`.

Keep a model when you want to select queries or run again with different inputs:

```python
from pathlib import Path

orders = pm.model(Path("examples/orders.malloy"), data_root="examples")
print(orders.query("orders.by_region").run().rows())
print(orders.queries)
orders.close()
```

Queries keep their model alive. Dropping the last reference allows cleanup, and
`close()` releases resources immediately. A model also supports `with pm.model(...)
as orders:` when a lexical scope suits the caller. Materialized results remain
usable after the model closes.

A string means Malloy text. Use `Path` for a file or `ModelSource` for a captured
model. Inline text defaults to `model.malloy` under `data_root`, or the current
directory. Pass `url=` to choose its import base. Files ending in `.malloynb` or
`.malloysql` are notebook documents. `document_kind="model"` or `"notebook"`
overrides filename detection, and a captured `ModelSource` retains that choice.

The `headless` extra supplies Deno, DuckDB, and PyArrow. Execution, SQL generation,
checks, formatting, and notebook preparation work without a browser or widget.

Pass `data_root="data"` to configure an owned connection's `file_search_path`.
DuckDB searches the process directory first. Use absolute paths when a particular
file must take precedence. Imports resolve relative to the model URL.
See [models](models.md) for query selection and [data access](data.md) for captured
inputs and borrowed connections.
