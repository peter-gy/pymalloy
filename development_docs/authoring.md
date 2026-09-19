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
Constructor-owned blocks carry layout metadata for nested indentation. Literal
SQL, comments and imported source text retain their own whitespace.
Named bindings have one expression child and optional owned annotation leaves. Binding
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
annotation routes owned by each binding. `.annotate(text, route=...)` replaces
that owned route, and `.doc(text)` selects the documentation route. Shared
statement annotations remain literal text so an edit cannot claim another
declaration's annotations.

`read_model` parses plain Malloy through the optional headless compiler.
`draft(*parts)` constructs syntax without runtime dependencies. Both return the
same `Draft`. The parser projects supported scalar expressions into operation
records. Python construction produces those same records through `col`, `lit`,
operators, aggregate methods, and namespaces. Python emission walks this tree
and emits source/query constructors for parser-recognized structure, including
handwritten models. Scalar operations become editable constructors. Grammar that
cannot be reconstructed retains its literal syntax with named editing scopes.
Unsupported scalar grammar is represented explicitly by `raw_expr`. Generated
code retains named editing scopes and captured imports.

The compiler wire contract distinguishes concrete syntax containers from scalar
leaves with a tagged union. Containers carry syntax parts. Scalar leaves carry
an operation tree and their original source spelling. Python protocol decoding
rejects mixed shapes. Identifier rendering sits below both syntax and scalar APIs.
Safe names remain unquoted. Reserved words come from the pinned Malloy lexer,
projected by `packages/core/scripts/lexicon.mjs` into Python `_authoring/lexicon.py` during
`pnpm records`. This build-time projection keeps pure Python construction
independent of the compiler process.

Scalar `.annotate()` retains the scalar type and attaches pending routed metadata.
`.doc()` selects the native documentation route. Binding consumes that metadata
into owned annotation syntax once. Source/query
fragments carry annotations as syntax. Python emission walks the resulting tree.

Reading and saving unchanged source preserves its exact text, including line
endings and comments. Imported scalar nodes keep their authored spelling until
edited or emitted as Python. Python emission serializes operations without a
source-text override, so editing an emitted operation changes rendered Malloy.
Supported expressions render canonically after the Python roundtrip. The contract
is semantic equivalence with preserved surrounding trivia, not identical scalar
spelling. Verify equivalent SQL and query results with the same source identity,
imports, data, and connection configuration.

## Semantic boundary

Malloy supplies expression semantics and type checking. Python builds operation
records without inferring field types. Scalar positions require `Expr`, and
ordinary values beside expressions become literals. `raw_expr` and `syntax` mark
additional scalar and source/query grammar respectively.

Opaque scalar subtrees make their entire enclosing imported expression opaque.
Parentheses in Malloy can change temporal range comparisons into point comparisons,
so partially reconstructing an unsupported literal is unsafe. Numeric token
spelling is retained with `number` when Python numeric construction would change
its inferred type.

## Validation and persistence

`Draft.check` returns compiler diagnostics in `CheckReport`. A supplied
`DocumentationPolicy` adds checks from compiled annotation metadata for missing
descriptions on the selected objects. Documentation lint is opt-in. Business meaning,
keys, and join cardinality require executable evidence and review.

`Draft.validate` compiles once, captures imports, runs named source/query
fragments as counterexample queries under one timeout budget, and closes the model on every path. Failed
compilation skips assertions. A failed assertion retains one counterexample.
Borrowed connections remain caller-owned, including transaction recovery after
engine errors. Preview limits bound returned rows, not scan cost or nested values.

The public validation module owns reports and documentation diagnostics. The
private headless adapter owns compilation and assertion execution. Draft execution
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

The asset build stages the root plugin and `skills/pymalloy` under
`pymalloy/_assets/agent`. Standard Hatch packages those assets in wheels and source
archives. Guidance access and syntax construction use base dependencies.
Parser-backed reading, compilation and execution require
the headless extra.

Verify semantic Python roundtrips and unchanged-file preservation on upstream
models, scoped edits, source/query behavior, closed imports, stale writes, failed assertions, and installed skill discovery.
Run base-only construction and generated-Python reconstruction with Deno and
DuckDB absent. Test the installed artifacts as well as the source checkout.

## Source artifacts and failures

The Python export layer materializes a closed `ModelSource` graph. Native import
literal spans and table-call ranges identify changes. Data bindings are explicit,
and SQL readers retain their authored SQL. No filesystem semantics enter core.
`Validation.source` exposes the accepted graph. Export checks syntax and import
closure. Recompilation and execution against copied inputs belong to the caller's
relocation verification. Bundle creation does not run those queries.

Runtime compilation retains the source graph and compiler version. An engine
failure wraps the original exception with detached query evidence. Source imports
read during ad hoc compilation are retained for replay. Schema errors preserve
DESCRIBE SQL through the compiler's exception chain.

`NativeMetadata.annotations` projects stable source and field annotations through
Malloy's exported `routeOf` and `payloadOf` helpers. Python documentation policy
selects routes and severity from that projection. It does not parse annotations.
The syntax editor replaces requested owned routes and preserves other routes
and shared annotation ownership.

## Captured input ownership

`_model/inputs.py` owns immutable Arrow IPC snapshots and once-only Parquet
materializations. IPC serialization retains Python-owned bytes. Parquet
verification reads bounded batches and checks exact values, schemas, and row
counts. A native table-reference node carries its optional input owner through
composition. The compiler sees an ordinary DuckDB path and has no Arrow dependency.

Runtime models, queries, execution evidence, and validations retain input owners
independently of connection lifetime. Extracting `ModelSource` retains source
text only. Widget definitions pair logical paths with Parquet bytes without loading
the headless adapter.

The producer notebook or script owns dataframe preparation and its dependency
graph. Bundling publishes accepted snapshots without executing that producer.
Explicit `files` bindings are copied at export time and are not validation-time
data snapshots. Input capture IDs distinguish origins from content hashes.

Bundle rewriting indexes source lines once and applies reference edits in one
forward pass. Copied files are hashed once per destination, including shared
Parquet assets. Physical deduplication preserves each input's identity.

Measure syntax, compilation, and capture costs with the
[authoring and dataframe benchmarks](testing.md#measure-authoring-and-dataframe-costs).
Record workload, dependency versions, and samples with each performance claim.
