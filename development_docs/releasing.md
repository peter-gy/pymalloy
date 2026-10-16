# Build and package

Complete [contributor setup](README.md), including the pinned Rust toolchain and
[cargo-about](https://embarkstudios.github.io/cargo-about/) license collector.
Build JavaScript assets, then package a native Python wheel and source archive
with [Maturin](https://www.maturin.rs/), the Rust/Python distribution builder:

```sh
pnpm build
uv build --package pymalloy --no-sources --out-dir dist/native
```

The native wheel contains the Python package, private `pymalloy._native`
extension, embedded Malloy compiler, browser widget assets, dependency notices,
and installed agent guidance. [PyO3](https://pyo3.rs/) exposes Rust to CPython.
Its `abi3-py312` target uses CPython's stable extension interface for Python 3.12
and newer. Operating systems and processor architectures have separate wheels.
Runtime requirements install DuckDB, PyArrow, and timezone data. Their
`sys_platform != 'emscripten'` markers let Pyodide install the browser package's
authoring and widget dependencies.

Native builds require the Rust toolchain pinned in
`packages/python/rust-toolchain.toml` and a C/C++ toolchain. `Cargo.lock` fixes the
resolved Rust dependency graph. Python wheel and editable builds enter the
private `build_backend.py`, which delegates to Maturin after verifying native
engine inputs. `--no-sources` checks that Python build requirements resolve
independently of local uv source overrides.

`native-archives.json` pins the [V8](https://v8.dev/) JavaScript engine archive and
generated Rust bindings for each target by URL, byte size, and SHA-256 digest.
`native_archive.py` checks the locked V8 version and selected features, verifies
downloaded files, and caches them in `CARGO_HOME/pymalloy-v8`. It also
[remaps Rust source paths](https://doc.rust-lang.org/rustc/remap-source-paths.html)
for the checkout, build home, Cargo cache, and Rust toolchain. Compiler-generated
paths in the extension use stable prefixes. Caller-supplied Rust flags are
preserved.
The first build needs network access for Rust
dependencies and these engine inputs. CI verifies the same inputs before its
direct Maturin builds.

## JavaScript assets

pnpm builds in dependency order. `scripts/stage-python.ts` copies the compiler,
widget, Pyodide runtime, per-artifact dependency notices, and agent guidance into
`pymalloy/_assets`. To build just Python's JavaScript dependencies:

```sh
pnpm --filter '@pymalloy/python...' build
```

`@pymalloy/compiler` emits one self-contained `compiler.js`. Its
`compiler.manifest.json` records the Malloy version, patch and protocol digests,
bundle digest, bootstrap revision, and embedded engine dependencies. Staging
checks current compiler inputs against the manifest. Rust's build script checks
staged compiler and widget assets before embedding the JavaScript bundle.
Rebuild after JavaScript source or dependency changes.

`@pymalloy/pyodide` emits the browser Python runtime as one closed `runtime.js`
bundle. Its manifest records the bundle and protocol digests and Malloy version.
Staging validates the digests before copying the runtime and its dependency
notices into `pymalloy/_assets/pyodide`. Browser-wheel packaging verifies the
staged runtime digest.

[anywidget-bundle](https://github.com/manzt/anywidget-bundle) builds the widget's
module graph. `BundledWidget` serves its bootstrap, manifest, chunks, extracted
StyleX stylesheet, and dependency notices from the installed distribution.
Static imports load with the app. Browser compilation, native
[Arrow](https://arrow.apache.org/docs/) columnar-data decoding, and the Malloy
result renderer have dynamic import boundaries. Keep every manifest-listed chunk
and the stylesheet in wheels and source archives. The native and browser builders
verify those files before packaging.

JavaScript dependency notices come from modules included in each build. Compiler
source maps remain beside build outputs.

`scripts/native-notices.ts` uses the cargo-about version pinned in
`packages/python/Cargo.toml` with the package's `about.toml`
and `about.hbs` to collect license texts for locked Rust runtime dependencies.
It fetches licenses for V8, [ICU](https://icu.unicode.org/) Unicode support, and
C++ runtime code from `native-licenses.json` and verifies their SHA-256 digests.
This asset-generation step needs network access.
Staging writes `native.LICENSE.txt` and `native.manifest.json`. The manifest
records the Rust lockfile, configuration, template, license-source list, and
notices digests. Staging also collects the locked web-platform JavaScript modules
in `native.runtime.json`, keyed by their `ext:` module specifiers. These modules
supply URLs, text encoding, blobs, and other JavaScript web APIs.
Rust's build script verifies the source digest and crate versions, then embeds
the modules in the extension. Runtime initialization resolves each extension
source through that embedded table.

## Browser wheel

[Pyodide](https://pyodide.org/en/stable/) runs Python in a browser. Build its pure
Python artifact explicitly with [Hatch](https://hatch.pypa.io/), after staging the
same widget and guidance assets:

```sh
uv --directory packages/python run --isolated --frozen --only-group release python -m hatchling build --target wheel --directory ../../dist/browser
```

`--isolated` gives the release tools a separate Python environment. The browser
wheel has the same distribution name and version as native wheels and the
`py3-none-any` wheel tag. It contains the Python facade, widgets, and
browser assets, including the asynchronous Python browser adapter and its
JavaScript runtime. Pyodide acceptance tests install its exact URL with the
runtime and dependency lock described in
[browser runtime pinning](testing.md#pin-the-browser-python-runtime). A fresh
consumer job checks the same artifact in standalone Pyodide, JupyterLite, and
marimo WebAssembly. Native notebook kernels install their platform's native
wheel. Keep the two artifact directories separate when selecting a wheel for tests.

## Source archive

The source archive includes Python and Rust sources, `Cargo.lock`, the private
build backend and archive verifier, pinned engine-input identities, prebuilt
compiler, widget, and Pyodide assets, native runtime JavaScript, manifests, notices, and
agent guidance. Rebuilding
uses Rust and a C/C++ toolchain. It can download Python build dependencies, Rust
dependencies, and the verified target V8 archive and bindings. JavaScript and
license notices come from the staged archive contents. Node.js and cargo-about
run during repository asset generation.

Build directly from the source archive:

```sh
uv build --wheel dist/native/pymalloy-*.tar.gz --out-dir dist/from-sdist
```

## Validate distributions

`pnpm canary` packs and installs the four public TypeScript packages, checks their
declarations in NodeNext and Bundler consumer projects, executes a Node query,
builds a browser consumer bundle, and runs that bundle through the exact-value
browser test. The browser server reads the bundle from `PYMALLOY_BROWSER_BUNDLE`.

Test each native wheel and a wheel rebuilt from the source archive on fresh
consumer runners, separate from the build jobs. Exercise parsing, formatting,
source editing, native queries, Arrow
results, widget construction, and agent guidance through a standard install.
Run compiler calls with external JavaScript runtimes unavailable, and retain
[browser tests](testing.md#browser-tests) against both
native notebook kernels and the browser artifact.

Check distribution metadata:

```sh
uv run --isolated --frozen --only-group release twine check dist/native/pymalloy-*.whl dist/native/pymalloy-*.tar.gz dist/browser/pymalloy-*.whl
```

## Preview documentation

Build and preview the deployed URL layout locally:

```sh
BASE_PATH=/pymalloy/ pnpm docs:build
BASE_PATH=/pymalloy/ pnpm docs:preview
```

## Publish a release

Set the Python version:

```sh
uv version --package pymalloy 0.2.0
```

Set `package.version` in `packages/python/Cargo.toml` to the same version, then
refresh the workspace package in the Rust lockfile and check alignment:

```sh
(cd packages/python && cargo update --workspace)
uv run --isolated --frozen --only-group release python scripts/check_release.py
```

Merge the version changes to `main`, then push an annotated tag:

```sh
git tag -a v0.2.0 -m "pymalloy 0.2.0"
git push origin v0.2.0
```

The release workflow checks the annotated tag against the Python and Rust
package versions and requires the tag to identify the checked-out commit. It
runs the same source checks as pull requests and builds native wheels for Linux
x86_64 and aarch64, macOS arm64 and x86_64, and Windows x86_64, alongside the
browser wheel and source archive. Linux wheels
use the `manylinux_2_28` compatibility floor. macOS wheels require macOS 12 or
newer. Each native wheel is tested on Python 3.12 and 3.14. Before attestation,
`scripts/check_release.py --distributions dist` validates all five native wheels,
the browser wheel, and the source archive. It checks versions, platform and
stable-ABI tags, embedded wheel metadata, extension payloads, and matching wheel
dependencies. The workflow collects validated artifacts for provenance
attestation and publishes them to PyPI through
trusted publishing from the `pypi` environment. The final job creates the GitHub
release with generated notes and the distributions.
