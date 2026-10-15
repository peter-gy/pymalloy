# Build and package

Build JavaScript assets before packaging Python with
[Hatch](https://hatch.pypa.io/), the Python distribution builder:

```sh
pnpm build
uv build --package pymalloy --no-sources
```

pnpm builds in dependency order. `scripts/stage-python.ts` copies the widget,
compiler, per-artifact dependency notices and installed agent guidance into
`pymalloy/_assets`. The widget's `widget/` directory contains the anywidget-bundle
bootstrap, manifest, JavaScript chunks, extracted StyleX stylesheet and dependency
notices. Notices come from the modules included in each build. Headless compiler
sourcemaps remain beside build outputs and are excluded from the wheel.
Hatch checks the required staged artifacts exist and are nonempty before building
a wheel or source archive. Missing assets fail the build with the `pnpm build`
instruction. The source archive includes this check and the built artifacts.
Rebuild after JavaScript source or dependency changes. `--no-sources` checks that
build requirements resolve independently of local uv source overrides.

To build just Python's JavaScript dependencies:

```sh
pnpm --filter '@pymalloy/python...' build
```

[anywidget-bundle](https://github.com/manzt/anywidget-bundle) builds the widget's module graph and `BundledWidget` serves it
from the installed Python distribution. Static imports load with the app. Browser
compilation, native [Arrow](https://arrow.apache.org/docs/) columnar-data decoding and the Malloy result renderer have dynamic
import boundaries. Keep every manifest-listed chunk and the stylesheet in wheel
and source archives. Hatch checks those files before packaging.

## Validate distributions

`pnpm canary` packs and installs the four public TypeScript packages, checks their
declarations in NodeNext and Bundler consumer projects, executes a Node query,
builds a browser consumer bundle, and runs that bundle through the exact-value
browser test. The browser server reads the bundle from `PYMALLOY_BROWSER_BUNDLE`.

Test isolated installs of the wheel and a wheel rebuilt from the source archive.
Verify that the base installation supports widget construction and agent
guidance with base dependencies. The headless installation must execute queries and return Arrow
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

## Publish a release

Set the version, merge it to `main`, then push an annotated tag:

```sh
uv version --package pymalloy 0.2.0
git tag -a v0.2.0 -m "pymalloy 0.2.0"
git push origin v0.2.0
```

`publish.yml` checks that the tag matches the package version, builds the wheel
and source archive, runs the installed-package tests, attests build provenance,
and publishes to PyPI through trusted publishing from the `pypi` environment.
It then creates the GitHub release with generated notes and the distributions.
