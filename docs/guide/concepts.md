# Concepts and boundaries

PyMalloy connects editable Malloy source to execution and portable files.
Malloy owns parsing, type checking, aggregate semantics, and SQL generation.
Python expressions build Malloy syntax. Runtime adapters supply imports, schemas,
and DuckDB execution.

## From source to results

```text
Draft.compile() → Model.query(...) → Query.run() → Result
                      │                 └─ sql() → SQL text
                      └─ source() → ModelSource

Draft.validate(checks) → Validation → bundle(...) → SourceBundle

Malloy file → export.prepare(...) → Document → notebook
```

| Value          | Responsibility                                                                                  |
| -------------- | ----------------------------------------------------------------------------------------------- |
| `Expr`         | A scalar expression such as `pm.col("amount").sum()`, resolved by Malloy                        |
| `Fragment`     | Reusable source or query syntax, including clauses and named editing scopes                     |
| `Draft`        | An immutable model revision, its source identity, optional captured imports, and managed inputs |
| `Model`        | Compiled source and discovered schemas, retained for query preparation and execution            |
| `Query`        | A selection within a model, or an ad hoc query, bound to givens when preparing SQL              |
| `Result`       | An Arrow table and Malloy column types with the executed SQL                                    |
| `ModelSource`  | Root URL, document kind, source text, and imports, independent of a live runtime                |
| `Validation`   | Diagnostics and outcomes of the supplied data assertions for one draft revision                 |
| `SourceBundle` | Paths to emitted Malloy, its data directory, and a manifest                                     |
| `Document`     | Ordered Markdown and query cells prepared for notebook serialization                            |

`pm.query(...)` constructs a query fragment. `model.query(...)` selects a query
on an already compiled model. A fragment has no connection and does not execute.
`pm.model(...)` accepts text, a `Path`, a draft, or a source snapshot.
`pm.run(...)` compiles and executes once, releasing resources before it returns.

## What gets captured

A compiled model retains imports and discovered schemas. Each execution reads
current data. Recompile after changing source or schema.

A `ModelSource` supplies all imports from its mapping. A missing import fails
instead of falling back to the filesystem or network. Constructing the record
checks its shape, while compilation or bundling checks whether referenced imports
are present. It contains neither table data nor a database snapshot.

`pm.data(frame)` captures materialized Python values and retains their verified
Parquet representation when first needed. Use it when Python-prepared data must
travel with a draft or widget. See [data access](data.md).

A source bundle materializes imports and copies explicitly bound files and managed
inputs. External SQL readers, catalog tables, remote services, and connection
settings still need review before treating it as self-contained.
[Bundle replay](bundles.md) describes the recorded evidence and remaining requirements.

## What checks establish

| Check              | Evidence                                                                          |
| ------------------ | --------------------------------------------------------------------------------- |
| Parsing            | Source is accepted by the installed Malloy parser                                 |
| Compilation        | Names, types, and schemas resolve for the configured data connection              |
| Documentation lint | Required objects have nonempty descriptions on accepted annotation routes         |
| Data assertions    | Supplied counterexample queries returned zero rows at validation time             |
| Replay comparison  | A re-executed query matches a recorded output under an explicit comparison policy |

`draft.check()` returns compiler diagnostics. Pass a `DocumentationPolicy` with
`documentation=` to also check descriptions. `draft.validate()` adds the supplied
data assertions. Calling it without assertions establishes no
additional data properties. A passing report does not establish that a metric or
question matches someone's intent. Grain, units, denominators, coverage, and null
meaning require explicit definitions and review.

Descriptions use Malloy's native annotation routes. PyMalloy exposes them and
checks their presence. Project-specific semantic records and visualization
constraints belong to the project producing the dataset.

## Execution and lifetime

Python models own a Deno compiler process and an owned or borrowed DuckDB
connection. Node and browser callers create a `Session` to own asynchronous work.
Browser sessions use DuckDB WebAssembly. Widgets own a browser session and publish
results asynchronously to Python.

`sql()` prepares SQL. `run()` executes it and materializes a result. Python results
retain Arrow tables, expose `.arrow()` directly, and materialize detached Python
values through `.rows()`. `.polars()` requires Polars.
JavaScript results expose `rows`, `columns`, `sql`, and a Malloy result tree for
rendering. Results remain usable after their runtime closes.

Operations serialize per Python model or TypeScript session. Queued cancellation
rejects that call. Active cancellation interrupts the current operation and waits
for it to settle before starting queued work. A healthy engine remains reusable.
A Python compiler-request timeout closes its model, since the compiler protocol
can no longer resume that request. Compiler process or worker failure also closes
the affected runtime.
Use `model.close()`, `session.close()`, or `widget.close()` for explicit release.
Borrowed connections remain caller-owned. See [model reuse](models.md) and the
[widget guide](widget.md) for their respective lifecycles.
