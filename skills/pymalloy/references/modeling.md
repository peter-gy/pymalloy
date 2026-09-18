# Modeling practices

Build definitions that answer the user's question and preserve the assumptions
needed to interpret the result.

## Discover and establish grain

Read existing Malloy files and their imports first. Inspect `model.inspect()` and
preview a few rows. Query distributions, null counts, duplicates, date coverage,
and sample key values before naming fields or choosing joins.

A declared `primary_key` is an assertion. Check duplicates and nulls separately.
For `join_one`, prove that the target key has at most one matching row. Check
unmatched foreign keys and compare totals before and after the join. A compiling
join can still encode the wrong relationship. Missing a declared key is not by
itself proof of incorrect aggregation: Malloy can synthesize distinct keys.

Validate assumptions through Malloy queries against the model being authored.
Use `.validate()` counterexamples for machine checks. Keep the query and the
finding together so the agent can explain what was tested.

## Define business meaning

Record grain, units, exclusions, and null handling in `#(doc)` descriptions.
Distinguish an observed fact from an assumed convention. Source-wide `where`
clauses affect every consumer. Confirm material scope and metric choices before
making them shared defaults, unless the user has already authorized the decision.

Do not infer revenue, canonical timestamps, or category boundaries from column
names. Compare alternative definitions with actual queries. Use user-supplied or
distribution-backed thresholds. Label unresolved assumptions in the model's docs.

Keep raw columns available without redeclaring them. Add dimensions for derived
values or meaningful aliases, measures for reusable aggregations, and saved views
for questions worth asking again. Use Python scalar expressions for field references, arithmetic, predicates, and
aggregates. Malloy compiles their semantics. Use `raw_expr` for scalar grammar
outside the constructor API. Compose additional source or query clauses with `pm.syntax(text)` and complete
declarations with `Draft.append(text)`. Use `pm.read_model(text)` to expose named
expressions in existing Malloy for scoped edits.

## Compose and parameterize

Start with one domain file for analysis-led work. Split base sources and joined
sources when reuse or size warrants it. Schema-led projects can establish one
base source per table and compose domain sources. Avoid speculative fields and
views that no question needs.

Use `draft.define(regional_orders=pm.ref("orders").extend(...))` to derive a
source while keeping the existing source's meaning. Imports and definitions precede their consumers.
Expose tunable inputs as `given` parameters and pass values through `givens=`.
A non-neutral default or permanent source filter changes every later query.

Use `pm.col("denominator").nullif(0)` where zero is possible. Use `where` for row filters
and `having` for aggregate filters. Let the compiler diagnose syntax and type
errors.

For top-N results, add deterministic tie-breakers. `order_by: revenue desc, name`
can stabilize equal-revenue groups when name is unique at that result grain.
A row limit alone does not make a ranking reproducible. Check nested rankings too.

## Distinguish evidence

- Compiler checks establish language and schema compatibility.
- Documentation lint reports missing descriptions on sources, measures, and views.
- Data assertions test named claims against the current data.
- Human review establishes whether those claims match the intended business meaning.

A passed empty assertion can be vacuous on empty data. Add a data-presence check
when the claim requires populated inputs. Sampling can guide discovery but cannot
prove key uniqueness. Revalidate after changing data or imports.

## Sources informing this workflow

These practices synthesize Publisher's model-authoring guidance, reviewed at
commit `bc703c9e3b`:

- [Discover](https://github.com/malloydata/publisher/blob/bc703c9e3b/skills/malloy-discover/SKILL.md)
- [Build models](https://github.com/malloydata/publisher/blob/bc703c9e3b/skills/malloy-model/SKILL.md)
- [Model as you go](https://github.com/malloydata/publisher/blob/bc703c9e3b/skills/malloy-model-as-you-go/SKILL.md)
- [Correctness review](https://github.com/malloydata/publisher/blob/bc703c9e3b/skills/malloy-review/reference/rubric-correctness.md)

Compiler diagnostics from the installed PyMalloy version take precedence over
syntax examples written for other Malloy releases.
