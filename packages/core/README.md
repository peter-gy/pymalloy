# Malloy compiler

Compile Malloy with synchronous jobs and host-supplied source and schemas.

```ts
import { parseSource, formatSource } from "@malloy-runtime/compiler/tooling";

const source = "run: missing";
console.log(parseSource(source).symbols);
console.log(formatSource(source).source);
```

`@malloy-runtime/compiler/jobs` supplies synchronous jobs to hosts such as the
headless compiler service. `CompiledModel.begin({ url, source?, documentKind?, connection: {name, dialect} })` returns a job.
`job.step(fulfilled?)` returns needs or a result. Hosts supply URL text and Malloy
field definitions for each schema request. The compiler owns language semantics,
query descriptors, model snapshots, diagnostics, and ordered notebook cells.

Application consumers create models through `Session.open()`, `session.model()`,
and `model.query()` in the Node or browser package. Both adapters share the
compiler package's `Model`, `Query`, and `ToolingError` classes.

[Compiler API](https://peter-gy.github.io/pymalloy/reference/core)
