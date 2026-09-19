# Build and package

Build the JavaScript assets before packaging Python:

```sh
pnpm build
uv build --package pymalloy --no-sources
```

pnpm builds in dependency order. `packages/python/build.mjs` copies the widget,
compiler, per-artifact dependency notices and installed agent guidance into
`pymalloy/_assets`. Notices come from each bundle's included modules. External
sourcemaps remain alongside build outputs and are excluded from the wheel.
Hatch checks the required staged artifacts exist and are nonempty before building
a wheel or source archive. Missing assets fail the build with the `pnpm build`
instruction. The source archive includes this check and the built artifacts.
Rebuild after JavaScript source or dependency changes. `--no-sources` checks that
build requirements resolve independently of local uv source overrides.

To build just Python's JavaScript dependencies:

```sh
pnpm --filter '@pymalloy/python...' build
```

The widget build emits one minified module with its default export preserved.
Exported notebooks and Pyodide consume this self-contained module. Keep the
renderer features and stylesheet in the wheel when changing bundling options.

## Validate distributions

`pnpm canary` packs and installs the four public TypeScript packages, checks their
declarations in NodeNext and Bundler consumer projects, executes a Node query,
and builds a browser consumer bundle. Run that bundle through the
browser suite with `PYMALLOY_CONSUMER_CANARY=1 pnpm --filter @pymalloy/e2e exec
playwright test --project browser`.

Test isolated installs of the wheel and a wheel rebuilt from the source archive.
The base installation must support widgets and agent guidance without Deno or
native DuckDB. The headless installation must execute queries and return Arrow
results. Check [browser behavior against the built wheel](testing.md#browser-tests).

```sh
uv build --wheel dist/pymalloy-*.tar.gz --out-dir dist/from-sdist
```

Check distribution metadata:

```sh
uv run --frozen --only-group release twine check dist/pymalloy-*.whl dist/pymalloy-*.tar.gz
```

## Preview documentation

Build and preview the deployed URL layout locally:

```sh
BASE_PATH=/pymalloy/ pnpm docs:build
BASE_PATH=/pymalloy/ pnpm docs:preview
```
