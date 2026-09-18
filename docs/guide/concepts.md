# Models, queries, and execution

A Malloy model defines data and reusable queries. PyMalloy loads the model,
compiles a query to SQL, and runs it with DuckDB.

## Source text and data sources

This model defines a data source, two views, and a query:

```text
source: numbers is duckdb.sql('SELECT unnest([40, 2]) AS value') extend {
  view: entries is { select: value order_by: value }
  view: total is { aggregate: total is value.sum() }
}
run: numbers -> total
```

**Source text** is the Malloy program passed to `Malloy(...)` or
`session.model(...)`. A **data source** (`source:`) describes a dataset and its
fields. Use `duckdb.sql(...)` for a SQL query or `duckdb.table(...)` for a table
or data file.

A **schema** records field names and types. Malloy asks DuckDB for schemas to
check field references and generate SQL.

A **dimension** is a field or expression used to select, filter, or group data.
A **measure** is a reusable aggregate calculation, such as a sum or count.

## Models and views

A **model** is a set of Malloy definitions, possibly assembled from imported
files. A **view** is a reusable query attached to a data source. In the numbers
model, `entries` lists the values and `total` sums them.

**Exported definitions** are available to other Malloy files that import the
model. PyMalloy exposes public views on exported data sources as query selectors.

`session.model(source)` retains definitions and discovered schemas. Loading reads
imports and inspects data without executing result queries. New rows are visible
on the next run. Reload after changing a schema or imported definition.

## Queries and selectors

A **query** describes a result. A `run:` statement selects a query to execute.
The numbers model runs its `total` view and returns `42`.

A **query selector** identifies an existing query. Find selectors in
`model.queries` or the widget's `state["queries"]`:

| Selector        | Selects                                                 |
| --------------- | ------------------------------------------------------- |
| `numbers.total` | A public view on an exported data source                |
| `totals`        | A named Malloy query declared as `query: totals is ...` |
| `run:1`         | The first unnamed `run:` statement, numbered from one   |
| `sql:1`         | The first standalone SQL cell in a loaded document      |

Keep selector names distinct, including generated `run:N` and `sql:N` names.
See [query selection](/guide/models#select-a-query) for defaults and one-off queries.

## Givens

A **given** is a typed Malloy query parameter. The `givens` mapping supplies
values by name. Declarations require `##! experimental.givens`.
See [query parameters](/guide/givens) for defaults, overrides, and accepted values.

## Sessions and widgets

A **session** loads models and executes queries. Python and Node sessions own or
borrow a DuckDB connection. A browser session owns a DuckDB worker. Closing a
session releases owned resources and invalidates its models.

A **widget** connects Python inputs to a browser session and displays results.
The notebook's browser connection starts execution. A **state snapshot** records
the current status, queries, SQL, rows, and diagnostics. It is detached: changing
the snapshot does not change the widget.

Results arrive asynchronously. See [widget inputs and results](/guide/widget)
for updates and observation, or [choose a runtime](/guide/overview#choose-where-to-run).

## Compilation and execution

**Compilation** checks definitions and turns a query into SQL. **Execution**
sends SQL to DuckDB and reads the result. Compilation needs access to the same
tables and files as execution to discover their schemas.

**Diagnostics** are compiler messages with a severity and optional source
location. Use `session.check(...)` to read them, `syntax_only=True` to skip
imports and schema discovery, or `model.sql(...)` to compile without executing.
See [language tools](/guide/language-tools) for checking and inspection.

## Files and documents

A `.malloy` file contains definitions and queries. `.malloynb` and `.malloysql`
documents can interleave Markdown, Malloy, and SQL cells.

An **export document** (`pymalloy.exports.Document`) holds ordered `Markdown` and
`Query` cells and their data locations. A **renderer** converts it to marimo or
Jupyter notebook text.

Each query has a `kind`: `select` reads rows, and `copy` writes a file.
An **export profile** chooses how queries run: fixed SQL (`precompiled`), a
native Python model (`native`), or browser widgets (`widget`).

A **model source snapshot** ([`ModelSource`](/reference/python#modelsource)) holds
source text, imports, and their URLs, separately from data. **Hydration** loads
that snapshot into a runtime model using current schemas.

See [Export notebooks](/guide/export) for profile choices, cell ordering, and data access.
