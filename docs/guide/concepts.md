# Concepts and boundaries

[Malloy](https://docs.malloydata.dev/) owns parsing, types, aggregate semantics,
and SQL generation. PyMalloy builds Malloy syntax and supplies execution with
[DuckDB](https://duckdb.org/docs/stable/), an embedded SQL database.

## From definitions to results

```text
Expr → Source + View → Draft
                        │
Connection.model(draft) → Model.query(...) → Query.run() → Result
                            └─ source() → ModelSource
Connection.validate(draft, checks) → Validation → bundle(...) → SourceBundle
```

| Value         | What it holds                                                                                |
| ------------- | -------------------------------------------------------------------------------------------- |
| `Expr`        | A scalar operation, such as a field reference, comparison, or sum                            |
| `Source`      | A relation with fields, measures, joins, saved views, or a query pipeline                    |
| `View`        | A source-relative query stage defining grouping, projection, aggregation, or nesting         |
| `Draft`       | An immutable model revision with source identity, optional captured imports, and inputs      |
| `Connection`  | The native database owner and shared execution lock for its models                           |
| `Model`       | Compiled source, resolved imports, discovered schemas, and query descriptors                 |
| `Query`       | A selection that retains its model and binds givens when preparing SQL                       |
| `Result`      | Materialized data, column descriptions, and executed SQL                                     |
| `ModelSource` | A closed source graph and retained captured input owners                                     |
| `Validation`  | Diagnostics and supplied data-check outcomes for one draft revision                          |
| `Input`       | An immutable capture of Python data, including its identity and verified file representation |

Sources, views, expressions, and drafts build syntax before compilation.
A model retains schemas while queries read current data. Recompile after a source
or schema change. [Running queries](running.md) covers selection and lifetime.

## What gets captured

A `ModelSource` retains the root URL, document kind, text, imported text keyed by
URL, and captured inputs in `inputs`. Imports resolve from that mapping.
A missing import fails compilation. Construction checks the record's shape.
Compilation or bundling checks import closure.

`pm.data(frame)` copies materialized Python values into a retained
[Arrow](https://arrow.apache.org/docs/), a columnar data format, snapshot.
The first compilation or widget request materializes verified
[Parquet](https://parquet.apache.org/docs/), a columnar file format, bytes.
Drafts, snapshots, validations, and execution evidence keep those captures alive.
External files and database tables remain live dependencies.

A source bundle copies captured inputs and explicitly bound files. Its manifest
records source and file hashes, query selection, givens, and validation outcomes.
Review catalog tables, SQL readers, remote services, and connection settings
before treating it as self-contained. See [bundle replay](bundles.md).

## What checks establish

| Check                                | Evidence                                                                |
| ------------------------------------ | ----------------------------------------------------------------------- |
| `pm.parse`                           | The installed Malloy parser accepts the source                          |
| `connection.check`                   | Names, types, and schemas resolve with the configured connection        |
| Documentation policy                 | Selected objects have nonempty annotations on accepted routes           |
| `connection.validate(draft, checks)` | Each supplied counterexample query returned zero rows                   |
| Replay comparison                    | Results match recorded expectations under an explicit comparison policy |

Validation with an empty check mapping establishes compilation and any requested
documentation checks. Grain, units, denominators, coverage, and null meaning need
explicit definitions and review. A passing assertion describes the observed data
at validation time. It cannot establish future data quality or whether a metric
matches the intended question.

Descriptions use Malloy's native annotation routes. Dataset-specific intent,
review records, and visualization requirements belong to the producing project.

## Results and lifetime

A Python connection owns or borrows a DuckDB connection. Each model owns one
[Deno](https://docs.deno.com/) compiler process. Closing a model releases that
compiler. Closing the connection closes its child models and owned database.
Borrowed databases and transactions remain caller-owned.

Operations serialize across a Python connection's models. A SQL timeout interrupts
the statement and leaves a healthy model reusable. A compiler request timeout
closes the affected model. Results retain their materialized data after closure.

Node and browser callers use `Session` for asynchronous work. A widget owns a
browser session and publishes revision-bound results to Python.
[Widgets](widget.md) describes its asynchronous state.
