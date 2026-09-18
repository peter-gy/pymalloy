# Parameterize queries with givens

Givens are typed inputs declared in Malloy:

```python
import pymalloy as pm

source = """##! experimental.givens
given: minimum :: number is 10
source: orders is duckdb.sql('SELECT 42 AS amount')
run: orders -> { select: amount where: amount >= $minimum }
"""
query = pm.model(source).query()
print(query.run(givens={"minimum": 20}).rows())
print(query.sql(givens={"minimum": 50}))
```

Bindings apply to one call. Defaults remain available to subsequent calls.
Malloy validates types and required inputs. Python integers and JavaScript
bigints preserve exact integer values. Python also accepts dates, datetimes,
Decimals, arrays, and string-keyed mappings through the compiler value protocol.
Dates and datetimes become ISO strings, and Decimals become exact decimal strings.
Malloy still checks whether those values fit the declared given type.

Widgets accept finite JSON values, including Python integers larger than the
JavaScript safe-integer range. Assign a complete `widget.givens` mapping to
publish an update. Readback is immutable, so use
`widget.givens = {**widget.givens, "minimum": 20}` to replace one binding.
Exporters accept `givens=` and the CLI accepts `--givens JSON`.
