# Contributor workflow

Set up the JavaScript and Python workspaces from the repository root:

```sh
pnpm install --frozen-lockfile
pnpm build
uv sync --frozen --all-packages --all-extras
```

Use Node 24.11 or newer and the pnpm version in `package.json`. CI reads Node,
Python, and uv versions from `.node-version`, `.python-version`, and
`pyproject.toml`. JavaScript dependencies use the pnpm catalog. Python uses `uv.lock`.

Build before syncing the Python workspace. The build compiles JavaScript, stages Python
runtime assets, and builds the public site.

| Task                                  | Start here                                    |
| ------------------------------------- | --------------------------------------------- |
| Choose the owner for a change         | [Architecture and ownership](architecture.md) |
| Extend model authoring and agent APIs | [Authoring architecture](authoring.md)        |
| Change widget or compiler messages    | [Protocols and lifecycle](protocol.md)        |
| Validate behavior across runtimes     | [Testing and compatibility](testing.md)       |
| Build distributions or publish        | [Build and release](releasing.md)             |

## TypeScript imports

Use extensionless relative imports in bundled TypeScript:

```ts
import { documentSource, sqlParts } from "./document";
```

Package and application configs inherit `tsconfig.base.json`. It uses
`moduleResolution: "Bundler"` and `module: "ESNext"` because Vite+ builds the
runtime code. Each package declares its own host types and libraries. The root
Oxlint configuration enforces the convention for relative module imports and
exports, including type imports.

Keep workspace dependencies as package names with `workspace:*` versions.
`vp pack` emits the public JavaScript and declarations referenced by package
exports, including their runtime file extensions. `pnpm canary` checks installed
packages under both NodeNext and Bundler resolution without skipping declaration
checks, then executes Node and builds a browser consumer.

Explicit extensions remain on real assets, external package subpaths, and the
anti-slop tooling executed directly by Node/Oxlint. Those paths resolve actual
files. Python schema generation uses source paths relative to its own config to
keep protocol records independent of declaration bundling.

## Validate a change

```sh
uv lock --check
pnpm check
pnpm test
pnpm canary
uv run --frozen pytest
uv run --frozen ruff format --check packages/python examples apps/e2e
uv run --frozen ruff check packages/python examples apps/e2e
uv run --frozen ty check
git diff --check
```

`pnpm check` runs formatting, type-aware Oxlint with anti-slop rules, typechecks,
and Knip. Use `pnpm check:knip` for unused-code and dependency checks alone.
Build first to provide workspace package declarations.

Keep the anti-slop rules and license together in `tools/oxlint/anti-slop`.
`vite.config.ts` documents exceptions for runtime decoding. Fix findings at their
owning boundary before adding exceptions.

Run `pnpm records` after changing compiler or widget records, or upgrading Malloy.
Commit the generated schema, `_protocol/records.py` and `_authoring/lexicon.py` keyword metadata
together. CI checks generation for drift.

Rebuild after changes to generated-asset inputs. Browser, widget, lifecycle, and
cross-language changes also require the [browser suite](testing.md#browser-tests).
Packaging changes require wheel and source-archive installation checks from
[build and release](releasing.md#validate-distributions).

Verify cross-runtime changes through each affected consumer API. Update package
exports, docs, examples, and lifecycle tests together.

## Work on documentation

Public pages live in `docs/`, contributor pages in `development_docs/`, and
VitePress configuration and theme in `apps/docs/.vitepress/`.

```sh
pnpm docs:dev
pnpm docs:build
```

Portless serves development at `https://docs.pymalloy.localhost` and preview at
`https://preview.docs.pymalloy.localhost`. Use the printed URL when your proxy
port or Git worktree changes it. Portless assigns the VitePress port. Its first
HTTPS setup may request administrator access to trust a certificate and bind
port 443.

Build output is in `apps/docs/.vitepress/dist`. Inspect desktop and narrow widths,
navigation, search, code blocks, and both themes. Keep titles, labels, links, and
terms consistent. Link every public page from the navigation.

Use the deployment base path when validating site links:

```sh
BASE_PATH=/pymalloy/ pnpm docs:build
BASE_PATH=/pymalloy/ pnpm docs:preview
```

Give each explanation a canonical home:

| Surface                                | Owns                                                                    |
| -------------------------------------- | ----------------------------------------------------------------------- |
| Root and Python package READMEs        | Shared capability summary, first examples, and links                    |
| `docs/guide/overview.md`               | Workflow and dependency choices                                         |
| `docs/guide/concepts.md`               | Public vocabulary and the scope of captured or checked evidence         |
| Other guides                           | One workflow per page with executable examples                          |
| `docs/reference`                       | Signatures, defaults, data shapes, failure behavior, and file contracts |
| `development_docs`                     | Package ownership, internal invariants, build, tests, and release       |
| `skills/pymalloy` and `pymalloy.agent` | Installed agent workflow and offline recipes                            |

Keep shared README examples in parity. Link to the owning page for detailed
contracts. Skills intentionally carry executable recipes for installed agents,
which may have no checkout or site access. Dataset-specific task records and
research evidence belong to the producing project.

## Upgrade a dependency

The compiler and document parser share a pin in `pnpm-workspace.yaml`.
Diagnose behavior against that installed version, not a newer upstream checkout.

1. Update the importing package or shared catalog, then run `pnpm install` or
   `uv lock`.
2. Review affected upstream contracts. For Malloy, check schema and given metadata
   in `packages/core/src/upstream.ts`, plus selectors, diagnostics, formatting,
   and document parsing. Keep report fields consistent across runtimes.
   For anywidget or traitlets, check initialization, validation, synchronization,
   and observers.
3. Run `pnpm build`. Test installed distributions after bundled dependency or
   build-tool changes.
4. Run the affected [semantic tests](testing.md#choose-tests-by-contract) and
   boundary checks. DuckDB and Arrow upgrades need precision, nested-value,
   path-resolution, and borrowed-connection cases.
5. For compiler changes, run the [upstream sample checker](testing.md#check-upstream-samples)
   and record the sample revision and outcomes.

Python dependencies use lower bounds. Test both the locked environment and
isolated public-index installations. A passing locked run does not establish
compatibility with every allowed dependency combination.
