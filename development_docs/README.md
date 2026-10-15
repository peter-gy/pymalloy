# Contributor workflow

Build JavaScript assets before installing the Python workspace:

```sh
pnpm install --frozen-lockfile
pnpm build
uv sync --all-packages --all-extras --frozen
```

[Node.js](https://nodejs.org/en/docs) runs the JavaScript tools. Use Node 24.11
or newer and the [pnpm](https://pnpm.io/) package-manager version in
`package.json`. `.node-version` records the development version.
[uv](https://docs.astral.sh/uv/) manages Python dependencies. Its minimum version
is in `pyproject.toml` and `.python-version` selects Python 3.12.

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
pnpm test
pnpm canary
pnpm e2e
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
Build first to supply package declarations. The Python type checkers inspect
`packages/python/src` using root `.venv` dependencies.

The [testing guide](testing.md) maps contracts to focused checks and describes
browser prerequisites. Packaging changes also need the
[distribution checks](releasing.md#validate-distributions).

## Continuous integration

GitHub Actions runs the validation list on every pull request and on `main`.
`.github/actions/setup` installs the locked Node.js, pnpm, and uv workspaces and
builds the packaged assets once per job.

| Workflow      | Jobs                                                                                 |
| ------------- | ------------------------------------------------------------------------------------ |
| `ci.yml`      | Lint and type checks, JavaScript tests, Python 3.12 and 3.14, lower bounds, browsers |
| `pages.yml`   | Builds the site for pull requests and deploys `main` to GitHub Pages                 |
| `publish.yml` | Publishes a `vX.Y.Z` tag to PyPI with provenance and creates its GitHub release      |

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
`scripts/test-python-floors.sh` builds the wheel, installs it with every runtime
and `headless` dependency pinned to its declared lower bound, and runs the Python
suite against that installation. CI runs it on every change. Lower a bound only
when that script passes with the new floor.
