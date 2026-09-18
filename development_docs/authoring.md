# Model authoring architecture

Python composition and imported Malloy share one immutable syntax representation.
Malloy owns parsing, source resolution, type checking, formatting, and SQL
compilation. Authoring operations name and replace expressions while preserving
the text that surrounds them.

## Representation and editing

A `Fragment` contains ordered literal strings, child fragments, and scalar `Expr`
leaves. Scalars own their operations independently of source/query composition.
Their immutable operation records are shared with the compiler projection.
Operators reuse existing records, while decoding freezes incoming sequences once.
Construction validates source metadata independently of rendering. Bulk definitions
and replacements resolve their named bindings together. Each immutable fragment
owns its lazy scope index and rendered-text cache, and new fragments start with
fresh caches. Malloy text rendering uses an explicit work stack and joins emitted
pieces once, so long expressions do not consume the Python call stack.
Named bindings have one expression child and optional owned documentation leaves. Binding
prefixes and suffixes retain names, other annotations, comments, and punctuation.
Anonymous fragments compose expressions and clauses. A `Draft` owns the document fragment, source URL, captured imports,
and the original file revision used for persistence checks.

`table`, `sql`, and `ref` construct source expressions. `dimension`, `measure`,
`view`, and query clauses construct fragments. `extend` and `pipe` compose them.
`Draft.define` and `Draft.queries` assign declaration names. A binding is the
editing boundary, so replacing a field in a source cannot silently change a
same-named field inside a nested view or join.

The compiler projects named source, query, field, and explicit join bindings from
Malloy's parser. Unrepresented grammar remains literal text between those
bindings. This keeps new Malloy syntax usable without a Python grammar change.
Schema validation remains a separate compiler operation. The parser identifies
single-line `#"` tags owned by a binding. Supplying `.doc(...)` in a replacement
replaces those leaves. Shared statement tags and block annotations remain opaque
text, so the editor cannot accidentally claim or erase another declaration's
documentation.

`read_model` parses plain Malloy through the optional server compiler.
`draft(*parts)` constructs syntax without runtime dependencies. Both return the
same `Draft`. The parser projects supported scalar expressions into operation
records. Python construction produces those same records through `col`, `lit`,
operators, aggregate methods, and namespaces. Python emission walks this tree
and emits editable scalar constructors inside `pm.draft` and `pm.syntax`.
Unsupported scalar grammar is represented explicitly by `raw_expr`. Generated
code retains named editing scopes and captured imports.

The compiler wire contract distinguishes concrete syntax containers from scalar
leaves with a tagged union. Containers carry syntax parts. Scalar leaves carry
an operation tree and their original source spelling. Python protocol decoding
rejects mixed shapes. Identifier quoting sits below both syntax and scalar APIs.

Scalar `.doc()` retains the scalar type and attaches pending field documentation.
Binding consumes that metadata into owned annotation syntax once. Source/query
fragments carry annotations as syntax. Python emission walks the resulting tree.

Reading and saving unchanged source preserves its exact text, including line
endings and comments. Imported scalar nodes keep their authored spelling until
edited or emitted as Python. Python emission serializes operations without a
source-text override, so editing an emitted operation changes rendered Malloy.
Supported expressions render canonically after the Python roundtrip. The contract
is semantic equivalence with preserved surrounding trivia, not identical scalar
spelling. Verify equivalent SQL and query results with the same source identity,
imports, data, and connection configuration.

## Design precedents

The source repositories informed three concrete choices:

- Ibis separates immutable expressions from operation nodes in
  [`ibis/expr/types/core.py`](https://github.com/ibis-project/ibis/blob/main/ibis/expr/types/core.py)
  and [`ibis/expr/operations/core.py`](https://github.com/ibis-project/ibis/blob/main/ibis/expr/operations/core.py).
  Its [`decompile`](https://github.com/ibis-project/ibis/blob/main/ibis/expr/decompile.py)
  walks that existing representation. PyMalloy likewise emits Python from its
  canonical syntax tree.
- Polars [`with_columns`](https://github.com/pola-rs/polars/blob/main/py-polars/src/polars/lazyframe/frame.py)
  normalizes named expressions before delegating to its native plan. PyMalloy uses
  keyword bindings and one expression conversion boundary, then delegates language
  semantics to Malloy.
- Mosaic's [`vgplot` grammar](https://github.com/uwdata/mosaic/blob/main/docs/api/vgplot/plot.md)
  composes independently reusable directives. PyMalloy clauses are values that can
  be composed, stored, and reused through one `extend(*clauses)` operation.

Malloy supplies expression semantics and type checking. Python builds a typed
operation tree without inferring field types. Scalar positions require `Expr`,
and ordinary values beside expressions become literals. `raw_expr` and `syntax`
mark the boundaries for additional scalar and source/query grammar respectively.

## Validation and persistence

`Draft.check` combines compiler diagnostics with documentation warnings in the
existing `CheckReport`. Documentation checks use compiled metadata and flag
missing descriptions on public sources, measures, and views. Business meaning,
keys, and join cardinality require executable evidence and review.

`Draft.validate` compiles once, captures imports, runs named source/query
fragments as counterexample queries under one timeout budget, and closes the model on every path. Failed
compilation skips assertions. A failed assertion retains one counterexample.
Borrowed connections remain caller-owned, including transaction recovery after
engine errors. Preview limits bound returned rows, not scan cost or nested values.

The public validation module owns reports and documentation diagnostics. The
private server adapter owns compilation and assertion execution. Draft execution
and root runtime exports use the same optional-dependency loader. Pure authoring
exports load directly and require no native engine or compiler process.

A validation report retains its immutable candidate. Saving the report cannot
write a later revision accidentally. Persistence publishes complete UTF-8 text
atomically and checks a loaded file against its original contents. It preserves
existing permissions. The revision check detects prior edits but does not lock
concurrent writers. Parent directories must already exist.

Validated saves with captured imports require the original root directory and
unchanged imported text. Save a draft and revalidate at its destination to relocate
it. Data and external files may change after validation.

## Agent workflow and distribution

The loop is discovery, composition, static diagnostics, data assertions, revision,
and persistence. Publisher's `malloy-discover`, `malloy-model`,
`malloy-model-as-you-go`, and `malloy-review` skills inform schema grounding,
verified grain, documented definitions, measured thresholds, and join checks.

`pymalloy.agent` introduces the public API and locates the installed
`skills/pymalloy` tree through `agent-plugins`. The Marimo capability entry point
loads this module. It contains discovery and documentation, with execution owned
by the ordinary Python API.

The root plugin and selected skill files ship through wheel, editable, and source
builds using `[tool.agent-plugins] root = "../.."`. Agent discovery and syntax
construction work with base dependencies. Parser-backed reading, compilation,
and execution require the server extra.

Verify semantic Python roundtrips and unchanged-file preservation on upstream
models, scoped edits, source/query behavior, closed imports, stale writes, failed assertions, and installed skill discovery.
Run base-only construction and generated-Python reconstruction with Deno and
DuckDB absent. Test the installed artifacts as well as the source checkout.

Opaque scalar subtrees make their entire enclosing imported expression opaque.
Parentheses in Malloy can change temporal range comparisons into point comparisons,
so partially reconstructing an unsupported literal is unsafe. Supported operations
use generated scalar records. Numeric token spelling is retained with `number`
when ordinary Python numeric construction would change its inferred type.

## Source artifacts and failures

The Python export layer materializes a closed `ModelSource` graph. Native import
literal spans and table-call ranges identify changes. Data bindings are explicit,
and SQL readers retain their authored SQL. No filesystem semantics enter core.
`Validation.source` exposes the accepted graph. Exported files are recompiled
against their copied inputs to verify relocation.

Runtime compilation retains the source graph and compiler version. An engine
failure wraps the original exception with detached query evidence. Source imports
read during ad hoc compilation are retained for replay. Schema errors preserve
DESCRIBE SQL through the compiler's exception chain.

`NativeMetadata.annotations` projects stable source and field annotations through
Malloy's exported `routeOf` and `payloadOf` helpers. Python documentation policy
selects routes and severity from that projection. It does not parse annotations.
The syntax editor replaces directly owned native descriptions and preserves
other routes and shared annotation ownership.

## Measure authoring latency

Run `uv run python tools/benchmark_authoring.py --output timings.json` to measure
fresh Python execution, parsing, draft formatting/checking/validation, compilation,
warm ad hoc query compilation, schema discovery, execution and result conversion.
The report retains samples, medians and dependency versions. Warm query edits use
one retained model. Cold starts use fresh Python processes but retain OS and Deno
caches. Schema discovery is measured directly through DESCRIBE, not inferred by
subtracting total compile times.

On the development Mac, five-sample medians for the 100,000-row benchmark measured
270 ms for draft formatting before sharing its compiler process and 137 ms after.
Draft compilation remained approximately 131 ms and warm ad hoc compilation
approximately 2.4 ms. These are local workload measurements, not performance
promises. The optimization changes process ownership for format-plus-parse and
introduces no cache.
