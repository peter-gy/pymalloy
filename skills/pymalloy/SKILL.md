---
name: pymalloy
description: Create, edit, inspect, and validate Malloy semantic models from Python. Use for schema discovery, measures, joins, saved views, compiler diagnostics, documentation checks, executable data assertions, and source bundles.
---

# PyMalloy model authoring

Use `import pymalloy as pm`. [Malloy](https://docs.malloydata.dev/) owns language
semantics. PyMalloy builds syntax, resolves schemas, executes queries, and records
evidence. The base package provides construction, widgets, and installed guidance.
Install `pymalloy[headless]` for parser-backed editing and native execution.
`pm.data` requires PyArrow. Install dataframe libraries directly.

## Ground and revise a model

1. Read existing source and imports. Use `pm.read_model(Path(...))` for a file or
   `pm.read_model(model.source())` for a retained graph. Reuse settled definitions.
2. Open `with pm.connect(...) as con`. Compile with `con.model(candidate)`.
   Inspect `model.inspect()` and `model.queries`. Preview a selected query with
   `model.query(name).preview(limit=5)`. Check grain, nulls, candidate keys, units,
   coverage, and relationships against real fields and values.
3. Compose `Source` declarations and `View` query stages. Name them with
   `draft.sources(...)` and `draft.queries(...)`. Edit a scoped field with
   `draft["orders"].replace(revenue=expression)`, then bind the returned source.
   Review `candidate.diff()` and affected assertions.
4. Run `con.check(candidate)` for names, types, and schemas. Pass
   `documentation=DocumentationPolicy()` from `pymalloy.validation` when required
   descriptions are part of acceptance.
5. Run `con.validate(candidate, checks, givens=...)`. Each named `Source` check
   returns counterexamples. Zero rows passes. Inspect diagnostics and failed
   checks before revising. `report.require_valid()` raises `ValidationError`
   from `pymalloy.errors` for rejected evidence.
6. Save accepted root source with `report.save(path)` or use
   `pymalloy.export.bundle(report, directory)` to copy inputs and imports.
   Reload after saving. Revalidate after changing data, imports, or location.

Use a model context manager when releasing its compiler before the connection.
Queries retain their model and connection. Preview limits bound returned rows,
while aggregates can still scan the full input. Validation shares one deadline
and closes its model before returning. Borrowed database settings, transactions,
and closure stay caller-owned.

Compiler success establishes language/schema compatibility. Counterexamples test
the supplied claims at validation time. Human review establishes whether grain,
cardinality, and definitions answer the intended question. Reuse decisions the
user settled and clarify unresolved choices when they materially change results.

## Choose the reference

- [API patterns](references/api.md): Source/View composition, expression strings,
  scoped editing, captured imports, and Python reconstruction.
- [Modeling practices](references/modeling.md): keys, joins, metric definitions,
  and deterministic ranking.
- [Artifact recipe](references/artifacts.md): validate, bundle, relocate, replay.
- [Failure triage](references/triage.md): compiler, schema, engine, and assertion evidence.

Read these through `pymalloy.agent.agent_skill().file(path).read_text()` when
working from an installed package. Public function docstrings own exact signatures
and parameter contracts. Keep dataset-specific intent and review records in the
producing project.
