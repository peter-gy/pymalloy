# Parameterize queries with givens

Givens are typed Malloy parameters. Use them to change query inputs without
rewriting the model. Declarations require `##! experimental.givens`.

With the [native Python runtime](/guide/native-python), supply overrides to
`model.run()`:

```python
from pymalloy.server import Session

with Session() as session:
    numbers = session.model("""
        ##! experimental.givens
        given: minimum :: number is 10
        source: numbers is duckdb.sql('SELECT unnest([2, 12, 42]) AS value')
        run: numbers -> {
          where: value >= $minimum
          select: value
          order_by: value
        }
    """)
    assert numbers.run()["value"].to_list() == [12, 42]
    assert numbers.run(givens={"minimum": 20})["value"].to_list() == [42]
    assert numbers.run()["value"].to_list() == [12, 42]
```

Overrides apply to one call. Later calls use the model's declared defaults.

For notebooks, see [exporting with givens](/guide/export#set-given-values).

## Choose values

Native Python givens accept strings, booleans, integers, finite floats, `None`, lists,
records, dates, datetimes, and decimals. Integers cross the compiler connection
exactly. Dates and datetimes use ISO strings, and decimals use numeric strings
accepted by Malloy. Numeric evaluation follows Malloy's number semantics. Use
timezone-aware datetimes for `timestamptz` givens.

## Update a displayed query

Pass `givens` to the widget, then assign a new dictionary to rerun it:

```python
from pymalloy import Malloy

filtered = Malloy(
    """
    ##! experimental.givens
    given: minimum :: number is 10
    source: numbers is duckdb.sql('SELECT unnest([2, 12, 42]) AS value')
    run: numbers -> { where: value >= $minimum select: value order_by: value }
    """,
    givens={"minimum": 20},
)
filtered
```

The widget displays `42`. Assign `filtered.givens = {"minimum": 10}` to display
`12` and `42`. Widget givens accept strings, booleans, integers, finite floats,
`None`, lists, and string-keyed dictionaries. Assign complete dictionaries to
notify the browser. Given changes reuse the compiled model.

See Malloy's
[language documentation](https://docs.malloydata.dev/documentation/) for type
declarations and the [native Python API](/reference/server) for call signatures.
