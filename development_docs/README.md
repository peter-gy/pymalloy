# Contributor workflow

Install [Rust](https://rust-lang.org/tools/install/), the native compiler,
and a C/C++ toolchain, then build JavaScript assets before installing the Python
workspace. `packages/python/rust-toolchain.toml` pins the Rust toolchain:

```sh
pnpm install --frozen-lockfile
pnpm --filter @pymalloy/python setup:rust
pnpm build
uv sync --all-packages --frozen
```

[Node.js](https://nodejs.org/en/docs) runs the JavaScript tools. Use Node 24.11
or newer and the [pnpm](https://pnpm.io/) package-manager version in
`package.json`. `.node-version` records the development version.
[uv](https://docs.astral.sh/uv/) manages Python dependencies. Its minimum version
is in `pyproject.toml` and `.python-version` selects Python 3.12.
[cargo-about](https://embarkstudios.github.io/cargo-about/) collects license texts
for the locked Rust dependencies during `pnpm build`. `setup:rust` installs the
package's pinned Rust toolchain and Cargo tools from
`packages/python/Cargo.toml`. Keep `CARGO_HOME/bin` on `PATH`, which defaults to
`~/.cargo/bin` with a standard Rust installation. Asset generation also
fetches the SHA-256-pinned external license sources in
`packages/python/native-licenses.json`. These steps need network access.

| Task                                 | Documentation                     |
| ------------------------------------ | --------------------------------- |
| Choose an owner or change a boundary | [Architecture](architecture.md)   |
| Choose a contract test or benchmark  | [Testing](testing.md)             |
| Package distributions                | [Build and package](releasing.md) |

## Validate a change

Run from the repository root after building:

```sh
uv lock --check
pnpm check
pnpm --filter @pymalloy/python check:rust
pnpm --filter @pymalloy/python test:rust
pnpm --filter @pymalloy/python audit:rust
pnpm test
pnpm canary
pnpm e2e
uv run --isolated --frozen --only-group release python apps/e2e/pyodide/lock.py --check
uv run --frozen pytest -q
uv run --frozen pytest -m e2e -q
uv run --frozen ruff check packages/python examples apps/e2e scripts
uv run --frozen ruff format --check packages/python examples apps/e2e scripts
uv run --frozen ty check
uv run --frozen pyrefly check
uv run --frozen basedpyright
pnpm docs:build
git diff --check
```

`pnpm check` covers formatting, type-aware Oxlint and the repository's anti-slop
rules, TypeScript, generated-record freshness, and unused code/dependencies.
Build first to supply package declarations. `uv sync` compiles the native Python
extension through [Maturin](https://www.maturin.rs/), the Rust/Python package
builder. The private Python build backend first fetches the target's V8 archive
and Rust bindings and verifies their pinned SHA-256 digests. Its first build also
downloads Rust dependencies. The Python type checkers inspect
`packages/python/src` using root `.venv` dependencies.

The Rust commands select the package's pinned toolchain. `check:rust` checks
formatting and runs [Clippy](https://doc.rust-lang.org/clippy/), Rust's source
linter, with warnings treated as errors. `test:rust` exercises native ownership
transitions. Both verify the pinned V8 inputs before compiling.

`audit:rust` runs [cargo-shear](https://github.com/axodotdev/cargo-shear) to check
dependency usage and [cargo-deny](https://embarkstudios.github.io/cargo-deny/) to
check security advisories, licenses, versions, and dependency sources.
The audit refreshes the [RustSec](https://rustsec.org/) vulnerability database
and needs network access. `packages/python/deny.toml` owns dependency policy.
The crate's lint tables own Rust source policy, including safe Rust and explicit
error handling at the Python boundary.

The [testing guide](testing.md) maps contracts to focused checks and describes
browser prerequisites. Packaging changes also need the
[distribution checks](releasing.md#validate-distributions).

## Continuous integration

GitHub Actions runs the validation list on every pull request, on `main`, and on
release tags. `.github/actions/setup` installs the workspace and builds packaged
assets and the native extension. `.github/actions/setup-rust` reads the same
toolchain and Cargo tool pins as local commands and caches Rust dependencies,
compiled dependencies, and verified engine inputs.

| Workflow      | Jobs                                                                                        |
| ------------- | ------------------------------------------------------------------------------------------- |
| `ci.yml`      | Requires source checks and distribution targets through `Check`                             |
| `checks.yml`  | Rust policy and ownership, lint and types, JavaScript, Python, lower bounds, browsers, docs |
| `pages.yml`   | Builds the site for pull requests and deploys `main` to GitHub Pages                        |
| `wheels.yml`  | Builds and tests native wheels, the browser wheel, and a rebuilt source archive             |
| `publish.yml` | Publishes a `vX.Y.Z` tag to PyPI with provenance and creates its GitHub release             |

The release workflow calls `checks.yml` on the tagged commit. Publication waits
for source checks and the complete distribution set. Native wheel probes run on
fresh consumer runners outside the checkout on Python 3.12 and 3.14 for every
target. A separate browser-wheel consumer job installs the release artifact in
the pinned Pyodide runtime and checks real JupyterLite and marimo WebAssembly
notebooks. The [browser runtime lock](testing.md#pin-the-browser-python-runtime)
fixes runtime and dependency artifact identities. Rust caches are saved from `main`.
[Dependabot](https://docs.github.com/en/code-security/dependabot),
GitHub's dependency update service, groups monthly Cargo and GitHub Actions
updates for review.

## Work on documentation

Public pages live in `docs/`, contributor pages in `development_docs/`, and
[VitePress](https://vitepress.dev/), the documentation site builder, is configured
in `apps/docs/.vitepress`. Root and Python package READMEs share their opening
example and route list. Give each guide one reader task and each reference exact
signatures, defaults, return values, errors, and lifetime.

Python docstrings use NumPy-style Parameters, Returns, Raises, Notes, See Also,
and Examples sections as needed. Include small inputs, observable results, and
resource cleanup. `test_docstrings.py` executes public docstrings.
`test_docs_examples.py` executes each README and guide Python fence in a fresh
process with shared temporary example data. Reserve an immediately preceding
`<!-- not-executed -->` marker for examples requiring an interactive environment.

`pnpm docs:dev` starts the site through [Portless](https://github.com/vercel-labs/portless),
a local hostname proxy. It prints the worktree-specific URL.
`pnpm docs:preview` serves the built site. Its first HTTPS setup can require
administrator access to trust a certificate and bind port 443.
Build output lives in `apps/docs/.vitepress/dist`.

Validate links, heading anchors, navigation, local search, code blocks, tables,
and light/dark themes at desktop and narrow widths. Check the deployment base
with `BASE_PATH=/pymalloy/ pnpm docs:build` and the matching preview environment.

## Keep imports and generated contracts aligned

Bundled TypeScript uses extensionless relative imports and workspace package
names with `workspace:*` versions. Vite builds runtime exports and declarations.
Scripts run directly in Node and retain extensions for real files.
`scripts/` owns its dependencies and build utilities.

Run `pnpm records` after compiler/widget contract changes or a Malloy upgrade.
Review and commit `packages/protocol/schema/protocol.json`, Python
`_protocol/records.py`, and `_authoring/lexicon.py` together. Rebuild assets before
testing installed distributions. [Architecture](architecture.md#generated-contracts-and-assets)
defines generation ownership.

## Upgrade a dependency

1. Update the importing package or `pnpm-workspace.yaml` catalog. Run
   `pnpm install` for JavaScript or `uv lock` for Python. Preserve both lockfiles.
   Rust dependencies are pinned in `packages/python/Cargo.toml` and resolved in
   `Cargo.lock`. Update them from that package. When V8 changes, update the target
   archive and binding digests in `native-archives.json` and the external license
   sources in `native-licenses.json`.
2. Review the dependency's current contract. [Malloy](https://docs.malloydata.dev/),
   the language compiler, shares a pin with its document parser. Check schema,
   givens, diagnostics, formatting, and parsed spans against that installed pin.
   Rebase its patch in `patches/` when changing the pin.
3. Rebuild and run the affected contracts from the testing guide. For database
   and Arrow changes, include precision, nested values, file resolution, and
   borrowed transactions. For compiler changes, run the upstream sample checkers
   and record their sample revision.
4. Verify installed distributions after bundled dependency or build-tool changes.

pnpm 11 defaults to a 1,440-minute minimum release age for dependencies,
including transitive dependencies. Respect that [release-age policy](https://pnpm.io/settings/dependency-resolution#minimumreleaseage)
during upgrades. Wait for the release to age or review a narrowly scoped exception
before recording it in workspace configuration.

Published Python lower bounds need a separate environment.
`scripts/test-python-floors.sh` builds the wheel, installs every runtime dependency
at its declared lower bound, and runs the Python suite against that installation.
CI runs it on every change. Lower a bound only when that script passes with the
new floor.
