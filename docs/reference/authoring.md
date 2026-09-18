# Python authoring API

```python
import pymalloy as pm

candidate = pm.draft().define(
    orders=pm.table("orders.parquet").extend(pm.measure(revenue=pm.col("amount").sum()))
)
report = candidate.check(data_root="data")
```

## Scalar expressions

`col(*path) -> Expr` quotes each field-path component. `col("orders", "amount")`
references a joined field, while `col("orders.amount")` names one field containing
a dot. `given(name)` references a declared given. `lit(value)` accepts a string,
integer, finite float or `Decimal`, boolean, `date`, `datetime`, or `None`.
`number(text)` preserves the exact spelling of a finite numeric literal, including
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

`case((condition, value), ..., otherwise=value)` chooses values with symbolic
predicates. For example, `case((col("amount") > 100, "large"), otherwise="small")`
constructs a Malloy case expression.

`call(name, *arguments, receiver=None)` constructs a Malloy function call. A receiver is an explicit tuple of source-path
components for scoped calls. `raw_expr(code)`
retains scalar Malloy syntax outside the supported operation grammar. Malloy owns
function availability, types, aggregate scope, and evaluation. An opaque expression
is inserted verbatim when used alone and parenthesized when composed as an operand.
Supply context-sensitive forms, such as `created = @2022`, as one complete raw
expression. Imported scalars with unsupported subexpressions remain whole raw
expressions so temporal range and partial-filter semantics are preserved.

## Sources and clauses

Source constructors return immutable `Fragment` values. Scalar clause arguments
require `Expr` values, including documented expressions. Bare strings are rejected.
Construction uses base dependencies and performs no compilation.

| Constructor                                                                             | Meaning                                                                                   |
| --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `table(path: str \| Path)`                                                              | DuckDB table expression. `Path` explicitly denotes a file                                 |
| `sql(text: str)`                                                                        | DuckDB SQL source expression                                                              |
| `ref(name: str)`                                                                        | Quoted reference to one source or query name                                              |
| `dimension(**fields)`, `measure(**fields)`                                              | Named scalar expressions                                                                  |
| `view(**queries)`, `nest(**queries)`                                                    | Named query fragments                                                                     |
| `query(*clauses)`                                                                       | Query block                                                                               |
| `group_by(*fields, **named)`, `aggregate(*fields, **named)`, `select(*fields, **named)` | Query scalar fields                                                                       |
| `where(predicate)`, `having(predicate)`                                                 | Row or aggregate predicate                                                                |
| `order_by(*fields)`                                                                     | `Expr` or `.asc()` / `.desc()` sort values                                                |
| `limit(rows: int)`                                                                      | Nonnegative query row limit                                                               |
| `primary_key(field: str)`                                                               | Quoted key field name                                                                     |
| `join(name, source, *, on, kind)`                                                       | Source fragment and `Expr` predicate with explicit `one`, `many`, or `cross` relationship |

`ref` quotes one name. Use `ref("orders").pipe(ref("by_region"))` to apply a saved source view. Arbitrary binding names use `**{"display name": expression}`.

## Fragment

| Member                    | Behavior                                     |
| ------------------------- | -------------------------------------------- |
| `.text`                   | Rendered Malloy text                         |
| `.names`                  | Named expressions in this scope              |
| `[name]`                  | One named expression's right-hand side       |
| `.replace(**expressions)` | Replace named right-hand sides in this scope |
| `.extend(*clauses)`       | Append a source extension block              |
| `.pipe(*queries)`         | Append query pipeline stages                 |
| `.doc(text)`              | Add a Malloy documentation annotation        |

Operations return new fragments. When replacing a binding, `.doc(text)` replaces
its directly attached single-line `#"` annotations. Shared statement tags and
block annotations retain their original text. Omitting `.doc` preserves existing
documentation. Lookup stops at named scope boundaries. Missing
names raise `KeyError`, and duplicates in the same scope raise `ValueError`.

Pipeline stages inside one named query share an editing scope. If stages define
the same field name, `.replace` rejects that ambiguous name. Replace the containing
query with new query constructors, or edit the preserved fragments in its emitted
Python representation.

`syntax(*parts, kind="expression", name=None)` composes literal strings, nested
fragments, and scalar `Expr` leaves. Use it for source or query grammar outside the constructors.
`Draft.to_python()` emits this structure around native scalar operations. Named `source`, `query`, and `field`
bindings contain one expression child, optional documentation leaves, and clause
containers for syntax such as a join condition. Their surrounding strings retain names, other tags, comments, and
punctuation.

## Draft

`draft(*parts: str | Fragment, url=None, imports=None) -> Draft`

Compose a document verbatim. Raw strings are retained as text. Named editing
requires constructor-created bindings or `read_model`. `imports=None` resolves
imports live when compiled. A mapping supplies a closed import snapshot.

`read_model(source: str | Path | ModelSource, *, url=None) -> Draft`

Parse plain Malloy with the installed compiler and preserve its exact text.
Strings mean Malloy text, `Path` means a local file, and `ModelSource` carries
captured imports. Requires `pymalloy[server]`. Parsing establishes named editing
slots but does not resolve schemas or validate business meaning.

| Member                                                                                   | Behavior                                                                     |
| ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `.text`, `.url`, `.imports`, `.names`                                                    | Source text, identity, captured imports, and root declaration names          |
| `[name]`                                                                                 | Named source or query expression                                             |
| `.define(**sources)`                                                                     | Add or replace named source expressions                                      |
| `.queries(**queries)`                                                                    | Add or replace named query expressions                                       |
| `.append(*parts)`                                                                        | Append literal text or syntax verbatim                                       |
| `.include(url: str \| Path)`                                                             | Add an import to a live draft                                                |
| `.diff(previous=None)`                                                                   | Unified diff against another draft or the originally loaded file             |
| `.format()`                                                                              | Format with Malloy and rebuild editable syntax                               |
| `.to_python(name="model")`                                                               | Executable Python reconstructing scalar operations, syntax, URL, and imports |
| `.check(documentation=DocumentationPolicy(), **options)`                                 | `CheckReport` with compiler diagnostics and documentation warnings           |
| `.compile(**options)`                                                                    | Retained runtime `Model`, explicitly closable                                |
| `.validate(checks=None, *, givens=None, documentation=DocumentationPolicy(), **options)` | Revision-bound `Validation`                                                  |
| `.save(path=None, *, overwrite=False)`                                                   | Write root text and return its `Path`                                        |

`define` and `queries` preserve surrounding text when replacing an existing
right-hand side. Replacing a declaration of the wrong kind fails. New declarations
are appended in keyword order. Imports and dependencies must precede consumers.

Check, compile, and validate accept the data connection options of `pm.model`.
`format` and `to_python` preserve the draft's source identity. Generated Python
reconstructs syntax and import snapshots. Supported scalar operations render
canonically, so their spelling may change while their semantics remain equivalent.
Other syntax and comments stay verbatim. The reconstructed draft has no ownership
of the originally loaded file.

## Validation

`draft.validate(checks, givens=None, **options)` compiles once and executes a
mapping of names to source/query `Fragment` values, such as
`ref("orders").pipe(query(where(col("amount") < 0), select(col("id"))))`. Zero rows passes. A failed
check retains one row. The timeout budget covers compilation, metadata, and all
assertions. Owned runtime resources are closed before the report returns.

`Validation` exposes `draft`, `diagnostics`, `checks`, `error`, and `ok`.
Each `DataCheck` exposes `name`, `status`, `result`, `error`, and `diagnostics`.
Statuses are `passed`, `failed`, `error`, or `skipped`. Compiler errors, runtime
errors, and every nonpassed check make `ok` false.

`report.require_valid(warnings_as_errors=False)` returns the same report or raises
`ValueError`. `report.save(path=None, overwrite=False, warnings_as_errors=False)`
requires validity and saves the captured revision.

Documentation warnings concern public sources, measures, and views. They remain
advisory by default. Assertions provide evidence about the data at check time.

## Persistence

Saving a loaded draft checks that its root file still matches the original read.
Saving to an unrelated existing path requires `overwrite=True`. Writes replace the
file atomically. Reload after saving before editing again.

A validated snapshot with imports must be saved in its original root directory,
and imported files must still match their captured text. Saving writes the root
text. Relocate through `Draft.save()` and validate again at the destination.

## Documentation policy

`.doc(text)` emits Malloy's native `#"` description route. Other authored routes
remain intact. `DocumentationPolicy` is imported from `pymalloy.validation`:

```python
from pymalloy.validation import DocumentationPolicy

policy = DocumentationPolicy(routes=('"', 'business'), kinds=("source", "measure"), severity="error")
report = candidate.check(documentation=policy)
```

The default policy checks sources, measures and views for a nonempty native
description and reports warnings. Pass `documentation=None` to disable this lint.
Compiler diagnostics remain enabled. Error-severity findings make `report.ok`
false. `validate` accepts the same policy.
