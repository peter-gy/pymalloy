# Browser Python

`pymalloy.browser` runs Malloy queries in [Pyodide](https://pyodide.org/),
the Python runtime compiled for WebAssembly. The connection owns a DuckDB
WebAssembly worker and closes it when its asynchronous context exits.

```python
from pymalloy import browser

async with browser.connect() as con:
    model = await con.model("run: duckdb.sql('SELECT 42 AS answer')")
    result = await model.query().run()
    assert result.to_pylist() == [{"answer": 42}]
```

Use a notebook kernel that supports top-level `await`. The first connection
downloads DuckDB WebAssembly assets. Custom hosts must allow JavaScript string
evaluation, worker creation, WebAssembly compilation, and the asset fetches.

Await `con.check(source)`, `con.parse(source)`, `con.format(source)`, and
`con.read_model(source)` for compiler tooling. Await `model.inspect()` and
`model.query(name).sql()`, `.run()`, or `.preview(limit=5)` for bound queries.
Pass parameter values through `givens=`. Preview limits bound returned rows,
while aggregates can still scan the full input.

Bind captured `Source` inputs into a `Draft` before compiling it. Pass external
data and imported Malloy files through `files=` or a closed `ModelSource` graph.
A `Path` reads the root Malloy source from the kernel's virtual filesystem.

`result.to_pylist()` returns detached dictionaries. Integer values retain their
precision and decimals become `Decimal` values. Dates and timestamps are ISO
strings. Binary values are lists of byte integers.

Display `pm.MalloyWidget(model)` or `pm.MalloyWidget(model.query(name))` while
the connection is open. The widget borrows that connection. Display
`pm.MalloyWidget(result)` after closing it to inspect retained rows.

For use across notebook cells, keep `con = browser.connect()` and call
`await con.close()` when finished. `model.close()` invalidates its queries and
cancels its pending work. Connection closure drains pending operations and
releases its worker.
