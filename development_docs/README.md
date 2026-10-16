# Contributor workflow

[Pixi](https://pixi.prefix.dev/latest/installation/) installs the repository's
locked interpreters, compilers, and command-line tools. Install Pixi 0.81 or
newer and the [platform software development kit (SDK)](#host-prerequisites),
then run from the repository root:

```sh
pixi run --locked setup
```

Setup installs JavaScript dependencies, checks Rust tool versions, builds the
packaged assets, and installs the Python workspace with its native extension.
The first run needs network access for tool packages, language dependencies,
and verified [V8](https://v8.dev/) JavaScript engine inputs. `--locked` rejects
a manifest that disagrees with `pixi.lock`.

| Lockfile                     | Owns                                                                                                           |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `pixi.lock`                  | Python interpreters, Node.js, pnpm, uv, Rust, its quality tools, native compilers, and Linux browser libraries |
| `pnpm-lock.yaml`             | JavaScript package dependencies                                                                                |
| `uv.lock`                    | Python runtime, development, notebook-host, and release dependencies                                           |
| `packages/python/Cargo.lock` | Rust crate dependencies                                                                                        |

[Node.js](https://nodejs.org/en/docs) runs JavaScript tools,
[pnpm](https://pnpm.io/) installs their dependencies.
[uv](https://docs.astral.sh/uv/) manages Python environments, and
[Rust](https://www.rust-lang.org/) compiles the native extension. `pixi.toml` pins
Node 24.19.0, pnpm 11.10.0, uv 0.13.1, and Rust 1.99.0. Run repository commands
through `pixi run --locked` so they use these tools.

| Environment | Interpreter and dependencies                                        | Run                                |
| ----------- | ------------------------------------------------------------------- | ---------------------------------- |
| `default`   | Locked Python 3.12, native tools, Python workspace in `.venv`       | `pixi run --locked setup`          |
| `py314`     | Locked Python 3.14, native tools, Python workspace in `.venv-py314` | `pixi run --locked -e py314 setup` |
| `js`        | Node.js, pnpm, Git                                                  | `pixi run --locked -e js setup-js` |

uv uses the selected Pixi interpreter and resolves Python libraries from
`uv.lock`. Its automatic interpreter downloads are disabled. Run Python type
checks in `default`, where their project configuration reads `.venv`.

## Host prerequisites

The developer environment supports Linux x86_64 and ARM64 with
[glibc](https://www.gnu.org/software/libc/), the system C library, at version 2.35
or newer, macOS 14 or newer on Intel and Apple silicon, and Windows x86_64.
The [Playwright browser support matrix](https://playwright.dev/docs/intro#system-requirements)
requires Windows 11 or Windows Server 2019 or newer. Pixi supplies Linux C/C++
compilers, linkers, and Chromium shared libraries. The host supplies its kernel
and system C library.

On macOS, install [Xcode Command Line Tools](https://developer.apple.com/xcode/resources/)
to provide the Apple software development kit used for native linking:

```sh
xcode-select --install
```

On Windows, install [Visual Studio 2022 Build Tools](https://aka.ms/vs/17/release/vs_BuildTools.exe).
The repository's `.vsconfig` selects the Microsoft C/C++ compiler and Windows SDK
10.0.22621.0. From an elevated PowerShell in the repository root, run the
downloaded bootstrapper:

```powershell
Start-Process -FilePath .\vs_BuildTools.exe -ArgumentList '--config', '.vsconfig', '--quiet', '--wait', '--norestart' -Wait
```

Follow Microsoft's [installer command reference](https://learn.microsoft.com/en-us/visualstudio/install/command-line-parameter-examples?view=vs-2022)
when adding these components to an existing installation. Pixi's Windows compiler
package activates the installed Microsoft tools. `pixi.lock` identifies
[Conda binary package artifacts](https://docs.conda.io/projects/conda/en/latest/user-guide/concepts/packages.html),
while Microsoft and Apple supply their SDK payloads through their installers. Record the SDK versions when reproducing a native build.

## Validate a change

After setup, build the [browser wheel](releasing.md#browser-wheel) before the
browser suite, then run:

```sh
pixi lock --check
pixi run --locked check
pixi run --locked lint-workflows
pixi run --locked test
pixi run --locked floors
pixi run --locked canary
pixi run --locked install-browser
pixi run --locked browser
pixi run --locked docs
git diff --check
```

`check` validates lockfiles, release versions, Pyodide dependencies, JavaScript,
Python source and types, and Rust source and dependency policy. `test` runs
JavaScript, Python, installed-package, and Rust ownership suites. Choose their
individual tasks, such as `check-js`, `test-python`, or `test-rust`, for a focused
change. `pixi task list` lists the available tasks.

`check-js` covers formatting, type-aware Oxlint and repository lint rules,
TypeScript, generated-record freshness, and unused code/dependencies. Build
assets first to supply package declarations. Python installation compiles the
extension through [Maturin](https://www.maturin.rs/), the Rust/Python package
builder. The private Python build backend verifies the target's V8 archive and
Rust bindings before compiling.

`check-rust` checks formatting and runs [Clippy](https://doc.rust-lang.org/clippy/),
Rust's source linter, with warnings treated as errors. `test-rust` exercises
native ownership transitions. Both verify pinned V8 inputs before compiling.
`check-toolchain` checks the compiler and tools supplied by Pixi, including
[Cargo](https://doc.rust-lang.org/cargo/), Rust's package manager.

`audit-rust` runs [cargo-shear](https://github.com/axodotdev/cargo-shear) to check
dependency usage and [cargo-deny](https://embarkstudios.github.io/cargo-deny/) to
check security advisories, versions, and sources. The audit refreshes
the [RustSec](https://rustsec.org/) vulnerability database and needs network
access. `packages/python/deny.toml` owns dependency policy. The crate's lint
tables own Rust source policy.

Run the Python 3.14 consumer suites in their separate environment:

```sh
pixi run --locked -e py314 setup
pixi run --locked -e py314 test-python
pixi run --locked -e py314 test-installed
```

| Task                                 | Documentation                     |
| ------------------------------------ | --------------------------------- |
| Choose an owner or change a boundary | [Architecture](architecture.md)   |
| Choose a contract test or benchmark  | [Testing](testing.md)             |
| Package distributions                | [Build and package](releasing.md) |

## Continuous integration

GitHub Actions runs source checks and distribution builds on every pull request,
on `main`, and on release tags. `.github/actions/setup` installs the selected
locked Pixi environment. Each command activates that environment through
`pixi run --locked`. The documentation job uses `js`, and Python compatibility
jobs run Python 3.12 and 3.14 on Linux, macOS, and Windows, selecting `default`
or `py314`.

| Workflow      | Jobs                                                                                        |
| ------------- | ------------------------------------------------------------------------------------------- |
| `ci.yml`      | Requires source checks and distribution targets through `Check`                             |
| `checks.yml`  | Rust policy and ownership, lint and types, JavaScript, Python, lower bounds, browsers, docs |
| `pages.yml`   | Builds the site for pull requests and deploys `main` to GitHub Pages                        |
| `wheels.yml`  | Builds and tests native wheels, the browser wheel, and a rebuilt source archive             |
| `publish.yml` | Publishes a `vX.Y.Z` tag to PyPI with provenance and creates its GitHub release             |

Rust caches retain downloaded crate sources, Git dependencies, and verified V8
inputs. Compiled native targets are rebuilt in each job. Linux wheel compilation
runs inside the manylinux container using the Rust version declared in Pixi.
The [packaging guide](releasing.md) distinguishes developer host requirements
from wheel compatibility floors.

Publication waits for source checks and the complete distribution set. Native
wheel probes run on fresh consumer runners outside the checkout on Python 3.12
and 3.14 for every target. A separate browser-wheel consumer job installs the
release artifact in the pinned Pyodide runtime and checks real JupyterLite and
marimo WebAssembly notebooks. The [browser runtime lock](testing.md#pin-the-browser-python-runtime)
fixes runtime and dependency artifact identities. Rust caches are saved from
`main`. [Dependabot](https://docs.github.com/en/code-security/dependabot),
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

`pixi run --locked -e js pnpm docs:dev` starts the site through
[Portless](https://github.com/vercel-labs/portless), a local hostname proxy. It
prints the worktree-specific URL.
`pixi run --locked -e js pnpm docs:preview` serves the built site. Its first HTTPS
setup can require administrator access to trust a certificate and bind port 443.
Build output lives in `apps/docs/.vitepress/dist`.

Validate links, heading anchors, navigation, local search, code blocks, tables,
and light/dark themes at desktop and narrow widths. Check the deployment base
with `BASE_PATH=/pymalloy/ pixi run --locked -e js docs` and the matching preview
environment.

## Keep imports and generated contracts aligned

Bundled TypeScript uses extensionless relative imports and workspace package
names with `workspace:*` versions. Vite builds runtime exports and declarations.
Scripts run directly in Node and retain extensions for real files.
`scripts/` owns its dependencies and build utilities.

Run `pixi run --locked pnpm records` after compiler/widget contract changes or a
Malloy upgrade.
Review and commit `packages/protocol/schema/protocol.json`, Python
`_protocol/records.py`, and `_authoring/lexicon.py` together. Rebuild assets before
testing installed distributions. [Architecture](architecture.md#generated-contracts-and-assets)
defines generation ownership.

## Upgrade a dependency

1. Update the importing package or `pnpm-workspace.yaml` catalog. Run
   `pixi run --locked pnpm install` for JavaScript or `pixi run --locked uv lock`
   for Python. Rust dependencies are pinned in `packages/python/Cargo.toml` and
   resolved in its `Cargo.lock`. Run Cargo updates from that package through
   `pixi run --locked`. Update toolchain or system-package requirements in
   `pixi.toml`, then run `pixi lock`. Review the affected lockfile with each change.
   When V8 changes, update the target archive and binding digests in
   `native-archives.json`.
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
`pixi run --locked floors` runs `scripts/test_python_floors.py`, which builds the
wheel, installs every runtime dependency at its declared lower bound, and runs
the Python suite against that installation.
CI runs it on every change. Lower a bound only when that script passes with the
new floor.
