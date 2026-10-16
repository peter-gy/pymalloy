# Embedded Python compiler

`@pymalloy/compiler` bundles [Malloy](https://docs.malloydata.dev/) compiler jobs
for Python's native extension. It imports `@malloy-runtime/compiler`, shared
DuckDB schema conversion, and `@pymalloy/protocol`.

`session.ts` owns one retained model and one active job per JavaScript isolate.
`entry.ts` exposes private `start`, `step`, and `close` operations to the Rust
host. A step returns source and schema needs to Python, which fulfils them before
resuming the job. Python owns filesystem access and DuckDB execution. Query rows
remain in the Python data adapter.

Build with `pnpm --filter @pymalloy/compiler build`. Vite emits the self-contained
`dist/compiler.js` bundle and its dependency notices. The Python build stages
and verifies that bundle, then Rust embeds it in the native extension. The
widget uses its own browser runtime and bundle.
