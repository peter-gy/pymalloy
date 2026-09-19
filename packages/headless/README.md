# Python compiler host

`@pymalloy/headless` runs compiler jobs in Deno for Python models. It imports
`@malloy-runtime/compiler`, shared DuckDB schema conversion, and
`@pymalloy/protocol`.

`service.ts` owns one pending job and one retained model per process. `main.ts` connects that
service to length-prefixed JSON on stdin and stdout. Source and schema needs
return to Python between steps. Python owns DuckDB execution, so query rows
never pass through the compiler process.

Build with `pnpm --filter @pymalloy/headless build`. The Python build stages
`dist/headless.mjs` in the wheel. The optional `pymalloy[headless]` dependencies
provide Deno and DuckDB. The widget has its own browser runtime and bundle.
