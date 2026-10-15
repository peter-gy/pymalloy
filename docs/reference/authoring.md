# Python authoring API

Individual constructors and expression methods include parameter explanations,
examples, and related operations in their Python docstrings. IDE hovers and
`help(pm.data)`, `help(pm.col)`, or `help(pm.Expr.filter)` show those contracts.

```python
import pymalloy as pm

candidate = pm.draft().sources(
    orders=pm.table("orders.parquet").measure(revenue=pm.col("amount").sum())
)
report = pm.connect(data_root="data").check(candidate)
```

## Scalar expressions

`col(*path) -> Expr` quotes each field-path component. `col("orders", "amount")`
references a joined field, while `col("orders.amount")` names one field containing
a dot. `given(name)` references a declared given. `lit(value)` accepts a string,
integer, finite float or `Decimal`, boolean, `date`, `datetime`, or `None`.
`pymalloy.expressions.number(text)` preserves the exact spelling of a finite numeric literal, including
scientific notation and signed zero. Generated Python uses it when numeric spelling
affects the compiler-inferred type. It accepts numeric data, not expression code.

`Expr` values are immutable. Syntax fragments and drafts compare by identity. Arithmetic, comparisons, `&`, `|`, and `~` construct
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
immutable `Source` values. `view()` creates an empty `View`. Construction builds
Malloy text. `data` also captures an Arrow snapshot and requires PyArrow.

| Source method                           | Behavior                                  |
| --------------------------------------- | ----------------------------------------- |
| `.dimension(**fields: Expr)`            | Declare row-level fields                  |
| `.measure(**fields: Expr)`              | Declare reusable aggregate fields         |
| `.view(**views: View)`                  | Declare saved query stages                |
| `.primary_key(field: str)`              | Declare row identity                      |
| `.join_one(name, source, *, on)`        | Declare a to-one relationship             |
| `.join_many(name, source, *, on)`       | Declare a to-many relationship            |
| `.join_cross(name, source, *, on=None)` | Declare a cross join, optionally filtered |
| `.where(predicate: Expr)`               | Filter source rows                        |

Source declaration methods append clauses in authored order to one trailing
`extend` block. Malloy checks keys, field types, and relationship semantics.

| View method                    | Behavior                                      |
| ------------------------------ | --------------------------------------------- |
| `.group_by(*fields, **named)`  | Set the output grain                          |
| `.aggregate(*fields, **named)` | Choose aggregate values                       |
| `.select(*fields, **named)`    | Project detail fields                         |
| `.where(predicate: Expr)`      | Filter input rows                             |
| `.having(predicate: Expr)`     | Filter aggregate groups                       |
| `.nest(**views: View \| str)`  | Add nested results or saved views             |
| `.order_by(*fields)`           | Order fields or explicit Expr.asc/desc values |
| `.limit(rows: int)`            | Bound the output row count                    |

Positional strings in `group_by`, `aggregate`, `select`, and `order_by` name field
paths split on dots. Keyword values require `Expr`. `col("customer", "name")`
keeps explicit path components, while `col("customer.name")` names a field with
a literal dot. Strings beside expressions remain literal values.

Both types expose `.text`, `.names`, `.inputs`, `[name]`, `.replace(**definitions)`,
`.doc(text)`, `.annotate(text, *, route="")`, and `.pipe(*stages: View | str)`.
A pipeline string names a saved view. View clauses append to the final stage.
`Source.raw(*parts)` and `View.raw(*parts)` concatenate trusted text, sources,
views, and scalar expressions verbatim.

Lookup returns `Source` for source bindings, `View` for saved views and nests,
and `Expr` for fields. Draft query bindings return `Source`. Lookup stops at
named scope boundaries. Missing names raise `KeyError`, and duplicate names
raise `ValueError`. Replacements preserve surrounding text and annotations on
routes the replacement leaves unspecified.

Pipeline stages inside one named query share an editing scope. If stages define
the same field name, `.replace` rejects that ambiguous name. Replace the containing
query with new query constructors, or edit the preserved fragments in its emitted
Python representation.

`syntax(*parts, kind="expression", name=None)` composes literal strings, nested
fragments, and scalar `Expr` leaves. Use it for source or query grammar outside the constructors.
Named `source`, `query`, and `field` bindings contain one expression child,
optional annotation leaves, and clause containers for syntax such as a join
condition. `Draft.to_python()` emits readable constructors for supported structure
and uses `syntax(...)` for comments and grammar outside those constructors.

## Draft

`draft(*parts: str | Source | View, url=None, imports=None) -> Draft`

Compose a document verbatim. Raw strings are retained as text. Named editing
requires constructor-created bindings or `read_model`. `imports=None` resolves
imports live when compiled. A mapping supplies a closed import snapshot.

`read_model(source: str | Path | ModelSource, *, url=None) -> Draft`

Parse plain Malloy with the installed compiler and preserve its exact text.
Strings mean Malloy text, `Path` means a local file, and `ModelSource` carries
captured imports. Requires `pymalloy[headless]`. Parsing establishes named editing
slots but does not resolve schemas or validate business meaning.

| Member                                  | Behavior                                                                                 |
| --------------------------------------- | ---------------------------------------------------------------------------------------- |
| `.text`, `.url`, `.imports`, `.names`   | Source text, identity, captured imports, and root declaration names                      |
| `.inputs`                               | Captured input resources with names, row counts, fingerprints, and detached Arrow access |
| `[name]`                                | Named source or query expression                                                         |
| `.sources(**sources)`                   | Add or replace named source expressions                                                  |
| `.queries(**queries)`                   | Add or replace named query expressions                                                   |
| `.append(*parts)`                       | Append literal text or syntax verbatim                                                   |
| `.include(url: str \| Path)`            | Add an import to a live draft                                                            |
| `.diff(previous=None)`                  | Unified diff against another draft or the originally loaded file                         |
| `.format()`                             | Format with Malloy and rebuild editable syntax                                           |
| `.to_python(name="model", inputs=None)` | Executable Python reconstructing scalar operations, syntax, URL, and imports             |
| `.save(path=None, *, overwrite=False)`  | Write root text and return its `Path`                                                    |

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

`connection.validate(draft, checks, *, givens=None, documentation=None, timeout=None)` compiles once and executes a
mapping of names to `Source` values, such as
`source("orders").pipe(query(where(col("amount") < 0), select(col("id"))))`. Zero rows passes. A failed
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
`ValueError`. `report.save(path=None, overwrite=False, warnings_as_errors=False)`
requires validity and saves the captured revision.

Documentation lint runs when a `DocumentationPolicy` is supplied. Its default
severity is advisory. Assertions provide evidence about the data at check time.
Operational failures, including timeouts and compiler crashes, raise exceptions
rather than becoming validation findings.

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

`.doc(text)` emits Malloy's native `#"` description route. Use
`.annotate("bar_chart")` for a renderer tag or
`.annotate("unit=USD", route="business")` for an app annotation. Routed annotations
remain editable in imported models. `DocumentationPolicy` is imported from
`pymalloy.validation`:

```python
from pymalloy.validation import DocumentationPolicy

policy = DocumentationPolicy(
    routes=('"', "business"), kinds=("source", "measure"), severity="error"
)
report = pm.connect().check(candidate, documentation=policy)
```

Documentation lint is off by default. Passing `DocumentationPolicy()` checks
sources, measures, and views for a nonempty native description and reports warnings.
Compiler diagnostics remain enabled. Error-severity findings make `report.ok`
false. `validate` accepts the same policy.
