# Parameterize queries with givens

Givens are typed parameters declared in [Malloy](https://docs.malloydata.dev/).
The installed compiler requires its experimental givens flag:

```python
import pymalloy as pm

source = """##! experimental.givens
given: minimum :: number is 10
source: orders is duckdb.sql('SELECT 42 AS amount')
run: orders -> { select: amount where: amount >= $minimum }
"""
with pm.connect() as con:
    with con.model(source) as model:
        query = model.query()
        print(query.run(givens={"minimum": 20}).to_pylist())
        print(query.run(givens={"minimum": 50}).to_pylist())
        print(query.run().to_pylist())
```

Expected output:

```text
[{'amount': 42}]
[]
[{'amount': 42}]
```

Bindings apply to one call. Omitted bindings use declared defaults.
Omit `is 10` in the declaration to require a binding. Malloy checks required
inputs and their types when SQL is prepared. Use `pm.given("minimum")` in Python
authoring to reference the declared parameter.

Native Python accepts finite scalars, dates, datetimes, `Decimal`, arrays, and
string-keyed mappings through the compiler value protocol. Integers stay exact.
Dates and datetimes become ISO strings and decimals become exact decimal strings.
Malloy checks compatibility with the declared given type.

Widgets accept finite JSON values, including integers larger than JavaScript's
safe-integer range. Assign a complete mapping, such as
`widget.givens = {**widget.givens, "minimum": 20}`. Native `Decimal`, `date`, and
`datetime` objects must be encoded as widget-compatible values first.

Exporters accept `givens=`. The [CLI](../reference/cli.md) accepts `--givens JSON`.
Validation captures one set of bindings for every supplied data check.
