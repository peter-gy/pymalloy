# Reuse models and select queries

A `Model` retains definitions and schemas for repeated queries. Create one with
a [native Python session](/guide/native-python):

```python
from pymalloy.server import Session

with Session() as session:
    numbers = session.model("""
        source: numbers is duckdb.sql('SELECT unnest([40, 2]) AS value') extend {
          view: entries is { select: value order_by: value }
          view: total is { aggregate: total is value.sum() }
        }
    """)
    print(numbers.queries)
    result = numbers.run(query="numbers.total")

assert result.item() == 42
```

The selectors are `('numbers.entries', 'numbers.total')`. Pass full query source,
including `run:`, to extend a retained model for one call:

```python
with Session() as session:
    numbers = session.model("source: numbers is duckdb.sql('SELECT 42 AS value')")
    result = numbers.run("run: numbers -> { select: value }")

assert result.item() == 42
```

`session.run(source)` loads, executes, and releases a temporary model in one call.

## Load a file

Use `session.load(path)` for `.malloy`, `.malloynb`, or `.malloysql` files.
Imports resolve beside the file. Data paths use the same directory unless the
session sets `data_root`. For inline imports, use `session.model(source, base_dir="models")`.

## Select a query

Pass an entry from `model.queries` as `query=`:

| Selector           | Selects                                       |
| ------------------ | --------------------------------------------- |
| `orders.by_region` | Public view on an exported source             |
| `regional_totals`  | Named query (`query: regional_totals is ...`) |
| `run:1`            | First run statement, numbered from one        |
| `sql:1`            | First document SQL cell                       |

`model.run()` defaults to the final run statement. With no run statements, it
uses the sole available query or requires `query=` if there are several.

Pass either new query source or a selector, not both.

## Keep schemas current

New rows are visible on the next query. Reload the model after changing column
names, types, or imported definitions.

Closing a session invalidates its models. Use `model.close()` or a model context
manager to release one early. See the [native Python API](/reference/server) for
timeouts and errors. [Node](/reference/node) and [browser](/reference/browser)
models use the same selectors.
