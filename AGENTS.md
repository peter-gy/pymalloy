# PyMalloy

PyMalloy runs Malloy in a browser widget, in headless Python or native Node sessions, and
in exported notebooks. Malloy owns language semantics. Runtime adapters own
DuckDB execution, data access, and resource lifetime.

## Ownership

- `packages/core` holds compiler jobs and ordered document cells. Hosts fulfil source
  and field-schema requests. Keep filesystem and database runtime APIs in adapters.
- `packages/duckdb` owns shared DuckDB type conversion and result materialization.
- `packages/node` owns native Node sessions and native DuckDB data access.
  `packages/browser` owns DuckDB WebAssembly workers and virtual files.
- `packages/widget` owns anywidget synchronization and rendering. `MalloyWidget` in
  `packages/python` owns Python inputs and detached state snapshots.
- `packages/protocol` owns Python wire records shared by the widget and headless host.
- `packages/headless` owns the bundled Deno compiler service and framed stdin/stdout.
- `pymalloy._headless` owns optional headless dependencies, the Deno process, Python
  DuckDB connections, and deadlines. Keep the base widget import Deno-free.
- Exporters own format-specific serialization and reproducible notebook data access.
- `apps` compose packages. Public guides and reference live in `docs`, contributor
  guidance in `development_docs`, and the public site's configuration in `apps/docs`.

## Invariants

- Delegate Malloy parsing, model resolution, and SQL generation to the shared compiler.
- Use one data-access contract for schema discovery and execution. Resolve database
  identifiers with native DuckDB semantics before treating them as file paths.
- Give connections, workers, models, processes, and listeners explicit owners.
  Preserve caller ownership of borrowed connections and their transactions.
- Bind asynchronous widget results to the input revision that produced them.
  Closing a widget, Python model, or TypeScript session must settle work and
  release its owned resources.
- Preserve integer precision and nested values across runtime and widget boundaries.
- Generated notebook bytes must be deterministic for the same inputs, schemas,
  options, output path, and dependency versions. Keep COPY ordering intact.
- Build generated assets from their owning source and verify the packaged files
  through installation and browser tests.

## Validation

```sh
pnpm install --frozen-lockfile
pnpm build
uv sync --all-packages --all-extras
pnpm check
pnpm test
uv run pytest
uv run ruff check packages/python examples apps/e2e
uv run ty check
```

Add `pnpm e2e` for browser, widget, lifecycle, and cross-language changes. Add
`uv build --package pymalloy` and isolated installation for packaging changes.
Add `pnpm docs:build` and desktop/narrow inspection for documentation changes.
Keep dependencies scoped to the package that imports them and preserve both lockfiles.

Test consumer behavior through APIs, files, kernel results, and browser state.
Keep implementation trivia out of assertions. Document contracts and hidden
constraints, and remove comments that narrate ordinary code.

Read [contributor setup](development_docs/README.md) and
[architecture](development_docs/architecture.md) for build and ownership details.

Distribution contracts live in [the packaging guide](development_docs/releasing.md).
Keep package metadata and artifact verification aligned.
