# Python authoring API

`pymalloy.authoring` constructs sources, views, and editable drafts.
`pymalloy.expressions` constructs scalar operations.
[Malloy](https://docs.malloydata.dev/) resolves their language semantics.
All edits return immutable values. Constructors build syntax before compilation.
Python docstrings supply parameter examples for `help` and editor lookup.

```python
import pymalloy as pm

candidate = pm.draft().sources(
    orders=pm.sql("SELECT 42 AS amount").measure(revenue=pm.col("amount").sum())
)
with pm.connect() as con:
    report = con.check(candidate)
print(report.ok)
```

## Scalar expressions

`col(*path) -> Expr` quotes each field-path component. `col("orders", "amount")`
references a joined field, while `col("orders.amount")` names one field containing
a dot. `given(name) -> Expr` references a declared given. `lit(value) -> Expr` accepts a string,
integer, finite float or `Decimal`, boolean, `date`, `datetime`, or `None`.
`pymalloy.expressions.number(text)` preserves the exact spelling of a finite numeric literal, including
scientific notation and signed zero. Generated Python uses it when numeric spelling
affects the compiler-inferred type. It accepts numeric data, not expression code.

`Expr` values are immutable. Sources, views, and drafts compare by identity. Arithmetic, comparisons, `&`, `|`, and `~` construct
operations. Python values passed beside an expression become literals. Use
parentheses around comparisons when combining predicates. Expressions reject
Python truth testing and iteration. `.equals(other)` compares operation trees.

| Operation                                                                    | Behavior                                                  |
| ---------------------------------------------------------------------------- | --------------------------------------------------------- |
| `.sum()`, `.avg()`, `.min()`, `.max()`                                       | Aggregate values                                          |
| `count(*scope)`                                                              | Count source rows, optionally in a joined source path     |
| `.count_distinct()`                                                          | Count distinct nonnull values                             |
| `.is_null()`, `.is_not_null()`                                               | Null predicates                                           |
| `.fill_null(value)`, `.nullif(value)`                                        | Explicit null handling                                    |
| `.cast(type, safe=False)`                                                    | Malloy or native SQL cast                                 |
| `.filter(predicate)`                                                         | Filter an aggregate's input                               |
| `.asc()`, `.desc()`                                                          | Sort expression                                           |
| `.str.lower()`, `.str.upper()`, `.str.strip()`                               | String normalization                                      |
| `.str.length()`, `.str.contains(value)`                                      | String length or substring test                           |
| `.str.starts_with(value)`, `.str.ends_with(value)`, `.str.replace(old, new)` | String operations                                         |
| `.dt.year()`, `.dt.month()`, `.dt.day()`                                     | Date components                                           |
| `.dt.hour()`, `.dt.minute()`, `.dt.second()`                                 | Time components                                           |
| `.dt.date()`, `.dt.truncate(unit)`                                           | Date conversion or time bucketing                         |
| `.doc(text)`                                                                 | Return an `Expr` with documentation for its field binding |
| `.annotate(text, *, route="")`                                               | Attach a renderer or app annotation to its field binding  |

`case((condition, value), ..., otherwise=value)` chooses values with symbolic
predicates. For example, `case((col("amount") > 100, "large"), otherwise="small")`
constructs a Malloy case expression.

`pymalloy.expressions.call(name, *arguments, receiver=None)` constructs a Malloy function call. A receiver is an explicit tuple of source-path
components for scoped calls. `Expr.raw(code)`
retains scalar Malloy syntax outside the supported operation grammar. Malloy owns
function availability, types, aggregate scope, and evaluation. An opaque expression
is inserted verbatim when used alone and parenthesized when composed as an operand.
Supply context-sensitive forms, such as `created = @2022`, as one complete raw
expression. Imported scalars with unsupported subexpressions remain whole raw
expressions so temporal range and partial-filter semantics are preserved.

## Source and View

`table(path, *, connection="duckdb")`, `sql(text, *, connection="duckdb")`,
`data(frame, *, name=None, connection="duckdb")`, and `source(name)` return
immutable `Source` values. `view()` creates an empty `View`, and `view(name)`
references a saved view for refinement. Construction builds
Malloy text. `data` captures an [Arrow](https://arrow.apache.org/docs/) columnar
snapshot. A `Path` table argument becomes an absolute file
reference. A string retains native table/file spelling. `connection` names the
Malloy connection, default `"duckdb"`. `data`'s `name` argument defaults to a generated input name.
See [data capture](../guide/dataframes.md) for producer types and precision limits.

| Source method                           | Behavior                                              |
| --------------------------------------- | ----------------------------------------------------- |
| `.dimension(**fields: Expr)`            | Declare row-level fields                              |
| `.measure(**fields: Expr)`              | Declare reusable aggregate fields                     |
| `.rename(**names: str)`                 | Rename fields with new names mapped to existing names |
| `.view(**views: View)`                  | Declare saved query stages                            |
| `.primary_key(field: str)`              | Declare row identity                                  |
| `.join_one(name, source, *, on)`        | Declare a to-one relationship                         |
| `.join_many(name, source, *, on)`       | Declare a to-many relationship                        |
| `.join_cross(name, source, *, on=None)` | Declare a cross join, optionally filtered             |
| `.where(predicate: Expr)`               | Filter source rows                                    |

Source declaration methods append clauses in authored order to one trailing
`extend` block. Malloy checks field types and relationship syntax. Data assertions
establish key uniqueness and null behavior. Each declaration method returns a
`Source`, and each query clause returns a `View`. `limit` accepts a nonnegative
integer and rejects booleans. Empty field clauses raise `ValueError`. Invalid
argument types raise `TypeError`.

| View method                    | Behavior                                      |
| ------------------------------ | --------------------------------------------- |
| `.group_by(*fields, **named)`  | Set the output grain                          |
| `.aggregate(*fields, **named)` | Choose aggregate values                       |
| `.select(*fields, **named)`    | Project detail fields                         |
| `.calculate(**fields: Expr)`   | Calculate window values in the current stage  |
| `.where(predicate: Expr)`      | Filter input rows                             |
| `.having(predicate: Expr)`     | Filter aggregate groups                       |
| `.nest(**views: View \| str)`  | Add nested results or saved views             |
| `.order_by(*fields)`           | Order fields or explicit Expr.asc/desc values |
| `.limit(rows: int)`            | Bound the output row count                    |

Positional strings in `group_by`, `aggregate`, and `select` name field paths split
on dots. `select("*")` selects every field. `order_by` strings name one output
column. After `group_by("customer.name")`, use `order_by("name")`. A dotted
`order_by` string raises `ValueError`. Keyword field expressions require `Expr`.
`col("customer", "name")`
keeps explicit path components, while `col("customer.name")` names a field with
a literal dot. Strings beside expressions remain literal values.

Both types expose `.text`, `.names`, `.inputs`, `[name]`, `.replace(**definitions)`,
`.doc(text)`, `.annotate(text, *, route="")`, and `.pipe(*stages: View | str)`.
A pipeline string names a saved view. View clauses append to the final stage.
`view("by_region").limit(1).where(col("amount") > 0)` adds both clauses to one
refinement of `by_region`. A second `limit` in the same stage raises `ValueError`.
`Source.raw(*parts)` and `View.raw(*parts)` concatenate trusted text, sources,
views, and scalar expressions verbatim.

`calculate` accepts window expressions through `pymalloy.expressions.call`, and
`rename` maps each new name to an existing field:

```python
import pymalloy as pm
from pymalloy.expressions import call

orders = pm.sql("SELECT * FROM (VALUES ('N', 6), ('S', 4)) t(region, amount)").rename(
    booked="amount"
)
summary = pm.view().group_by("region").aggregate(
    revenue=pm.col("booked").sum()
).order_by("region").calculate(
    prior=call("lag", pm.col("revenue"))
)
with pm.connect() as con:
    result = con.model(pm.draft().queries(report=orders.pipe(summary))).query().run()
print(result.to_pylist())
# [{'region': 'N', 'revenue': Decimal('6'), 'prior': None}, {'region': 'S', 'revenue': Decimal('4'), 'prior': Decimal('6')}]
```

Use raw text for Malloy clauses such as `index`, `timezone`, `accept`, `except`,
source arguments, and joins using `with`. Malloy checks their grammar and types:

```python
import pymalloy as pm

orders = pm.Source.raw(pm.sql("SELECT 2 amount, 9 extra"), " extend { accept: amount }")
with pm.connect() as con:
    result = con.model(pm.draft().queries(report=orders.pipe(pm.view().select("*")))).query().run()
print(result.to_pylist())
# [{'amount': 2}]
```

Bind annotated views with `.view(totals=stage.doc("Totals"))`, or annotate a
complete query before `.queries(chart=query.annotate("bar_chart"))`. `pipe`
raises `ValueError` for an annotated stage because Malloy attaches annotations
to named bindings.

Lookup returns `Source` for source bindings, `View` for saved views and nests,
and `Expr` for fields. Draft query bindings return `Source`. Lookup stops at
named scope boundaries. Missing names raise `KeyError`, and duplicate names
raise `ValueError`. Replacements preserve surrounding text and annotations on
routes the replacement leaves unspecified.

Pipeline stages inside one named query share an editing scope. If stages define
the same field name, `.replace` rejects that ambiguous name. Replace the containing
query with new query constructors, or edit the preserved fragments in its emitted
Python representation.

`Draft.to_python()` emits authoring method chains for supported structure. It
retains other clauses through `Source.raw`, `View.raw`, or `Expr.raw`, and complete
statements through `Draft.append`.

## Draft

`draft(*parts: str | Source | View, url=None, imports=None) -> Draft`

Compose a document verbatim. Raw strings are retained as text. Named editing
requires constructor-created bindings or `read_model`. `imports=None` resolves
imports live when compiled. A mapping supplies a closed import snapshot.

`read_model(source: str | Path | ModelSource, *, url=None) -> Draft`

Parse plain Malloy with the installed compiler and preserve its exact text.
Strings mean Malloy text, `Path` means a local file, and `ModelSource` carries
captured imports. Native wheels include this parser. Parsing establishes named
editing slots. Use `Connection.check` or validation to resolve schemas and test
data assertions.

| Member                                         | Behavior                                                                                 |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `.text`, `.url`, `.imports`, `.names`, `.path` | Source text, identity, captured imports, root names, and original loaded path            |
| `.inputs`                                      | Captured input resources with names, row counts, fingerprints, and detached Arrow access |
| `[name]`                                       | Named source or query expression                                                         |
| `.sources(**sources)`                          | Add or replace named source expressions                                                  |
| `.queries(**queries)`                          | Add or replace named query expressions                                                   |
| `.append(*parts)`                              | Append text, sources, views, or declarations from another draft                          |
| `.include(url: str \| Path)`                   | Add an import to a live draft                                                            |
| `.diff(previous=None)`                         | Unified diff against another draft or the originally loaded file                         |
| `.format()`                                    | Format with Malloy and rebuild editable syntax                                           |
| `.to_python(name="model", inputs=None)`        | Executable Python reconstructing scalar operations, syntax, URL, and imports             |
| `.save(path=None, *, overwrite=False)`         | Write root text and return its `Path`                                                    |

`sources` and `queries` preserve surrounding text when replacing an existing
right-hand side. Replacing a declaration of the wrong kind fails. New declarations
are appended in keyword order. Imports and dependencies must precede consumers.

Use `connection.check(draft)`, `connection.model(draft)`, and
`connection.validate(draft, checks)` with an owner created by `pm.connect()`. A draft contains plain Malloy
model syntax, so it defaults to `document_kind="model"` independently of its URL.
`format` and `to_python` preserve the draft's source identity. `to_python` uses
Malloy's parsed structure to emit constructors for handwritten and generated
models. Supported clauses and expressions render canonically, which can change
whitespace, quoting, and numeric spelling while preserving meaning. Comments and
unsupported grammar remain literal syntax fragments. The original draft retains
its authored text until edited or formatted. The reconstructed draft has no
ownership of the originally loaded file.

## Validation

`pymalloy.validation.Validation` is produced by `Connection.validate`.
`pymalloy.validation.DataCheck` is a named assertion outcome in `.checks`.

`connection.validate(draft, checks=None, *, givens=None, documentation=None, timeout=None)` compiles once and executes a
mapping of names to `Source` values, such as
`source("orders").pipe(view().where(col("amount") < 0).select("id"))`. Zero rows passes. A failed
check retains one row. The timeout budget covers compilation, metadata, and all
assertions. Validation closes its compiler before returning the report.

`Validation` exposes `draft`, `diagnostics`, `checks`, `error`, `ok`, `givens`,
`connection_name`,
and available query names in `queries`. A successful report's `source` property
returns its accepted `ModelSource`. Invalid reports reject that access. Pass the
report itself to `bundle` to retain managed input owners and validated bindings.
Each `DataCheck` exposes `name`, `status`, `result`, `error`, `diagnostics`, and
`execution`. Engine failures retain detached execution evidence in `execution`.
Statuses are `passed`, `failed`, `error`, or `skipped`. Compiler errors, runtime
errors, and every nonpassed check make `ok` false.

`report.require_valid(warnings_as_errors=False)` returns the same report or raises
`pymalloy.errors.ValidationError`. `report.save(path=None, overwrite=False, warnings_as_errors=False)`
requires validity and saves the captured revision.

Documentation lint runs when a `DocumentationPolicy` is supplied. Its default
severity is advisory. Assertions provide evidence about the data at check time.
Operational failures, including timeouts and compiler boundary failures, raise
exceptions. The [runtime error contract](runtime.md#errors) describes compiler
lifetime and managed interruption.

## Persistence

Saving a loaded draft checks that its root file still matches the original read.
Saving to an unrelated existing path requires `overwrite=True`. Writes replace the
file atomically. Reload after saving before editing again.

A validated snapshot with imports must be saved in its original root directory,
and imported files must still match their captured text. Saving writes the root
text. Use [source bundles](export.md#source-bundles) to materialize the captured
graph, then revalidate at the destination.

Drafts with captured data require `bundle(connection.validate(draft), directory)` for
persistence. `.save()` cannot write managed inputs. `.to_python(inputs=...)`
maps input names to Python variable names and preserves shared source expressions.
It reconstructs the model grammar, not the producer of the dataframe.

## Documentation policy

`pymalloy.validation.DocumentationPolicy(routes=('"',),
kinds=("source", "measure", "view"), severity="warning")` is frozen.
Routes and kinds must be tuples of strings. Invalid types raise `TypeError`.
Severity must be `"warning"` or `"error"`, otherwise `ValueError` is raised.

`.doc(text)` emits Malloy's native `#"` description route. Use
`.annotate("bar_chart")` for a renderer tag or
`.annotate("unit=USD", route="business")` for an app annotation. Routed annotations
remain editable in imported models. `DocumentationPolicy` is imported from
`pymalloy.validation`:

```python
import pymalloy as pm
from pymalloy.validation import DocumentationPolicy

policy = DocumentationPolicy(
    routes=('"', "business"), kinds=("source", "measure"), severity="error"
)
candidate = pm.draft().sources(
    orders=pm.sql("SELECT 42 AS amount").measure(
        revenue=pm.col("amount").sum().doc("Booked amount in USD.")
    ).doc("One row per order.")
)
with pm.connect() as con:
    report = con.check(candidate, documentation=policy)
print(report.ok)
```

Documentation lint is off by default. Passing `DocumentationPolicy()` checks
sources, measures, and views for a nonempty native description and reports warnings.
Compiler diagnostics remain enabled. Error-severity findings make `report.ok`
false. `validate` accepts the same policy.

## Input

`pymalloy.authoring.Input` is produced by `pm.data`. It exposes read-only
`id`, `name`, `rows`, `fingerprint`, and `reference` properties. `to_arrow()`
returns detached Arrow values. `Source.inputs`, `View.inputs`, `Draft.inputs`,
and `ModelSource.inputs` retain these owners. Verified Parquet materializes
on demand and stays alive with its owner. Use `bundle` to persist it.
