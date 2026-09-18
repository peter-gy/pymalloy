# Run queries from Python

Install server execution, adding dataframe conversions when needed:

```sh
pip install 'pymalloy[server,dataframes]'
```

```python
import pymalloy as pm

result = pm.run("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }")
print(result.rows())  # [{'answer': 42}]
frame = result.polars()
```

`pm.run` compiles and executes a query, then releases its compiler and connection
before returning. The result owns its values. `result.sql` contains the executed
SQL and `result.columns` describes the columns. `arrow()` and `polars()` require
the `dataframes` extra.

Keep a model when you want to select queries or run again with different inputs:

```python
from pathlib import Path

orders = pm.model(Path("examples/orders.malloy"), data_root="examples")
print(orders.query("orders.by_region").run().rows())
print(orders.queries)
```

Models manage their own resources. Queries keep their model alive, and dropping
the last reference allows cleanup. Call `orders.close()` to release resources
early. A string means Malloy text. Use `Path` for a file or `ModelSource` for a
captured model.

The `server` extra supplies Deno and DuckDB. Execution, SQL generation, checks,
formatting, and notebook compilation work without a browser or widget.

Pass `data_root="data"` to configure an owned connection's `file_search_path`.
DuckDB searches the process directory first. Use absolute paths when a particular
file must take precedence. Imports resolve relative to the model URL.
See [models](models.md) for query selection and [data access](data.md) for Python
tables and borrowed connections.
