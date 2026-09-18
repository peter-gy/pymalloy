# Build and release

Build the JavaScript assets before packaging Python:

```sh
pnpm build
uv build --package pymalloy --no-sources
```

pnpm builds in dependency order. `packages/python/build.mjs` copies the widget,
compiler, and production dependency notices into `pymalloy/_assets`.
Hatch checks that all four staged artifacts exist and are nonempty before building
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

CI tests isolated installs of the wheel and a wheel rebuilt from the source
archive. It checks base imports, a server query, and
[browser behavior against the built wheel](testing.md#browser-tests).

Check distribution metadata:

```sh
uv run --frozen --only-group release twine check dist/pymalloy-*.whl dist/pymalloy-*.tar.gz
```

## Publish

Prepare a version change and merge it after CI passes:

```sh
uv version --package pymalloy --bump patch
uv lock
```

Tag the release commit on `main`:

```sh
git switch main
git pull --ff-only origin main
version="$(uv version --package pymalloy --short)"
git tag -a "v$version" -m "Release $version"
git push origin "v$version"
```

The publish workflow verifies the annotated tag against the package version,
runs CI, and uploads the tested distributions through PyPI Trusted Publishing.
Configure the publisher with repository `peter-gy/pymalloy`, workflow `publish.yml`,
and environment `pypi`.

Published versions cannot be overwritten. If upload is interrupted, rerun the
failed job. `uv publish --check-url` checks files already present on PyPI.

## Deploy documentation

CI calls `.github/workflows/pages.yml` to build the site. Runs on `main` deploy
to `https://peter-gy.github.io/pymalloy/` using the `github-pages` environment.
Set **Settings → Pages → Build and deployment → Source → GitHub Actions**.

Preview the deployment path locally:

```sh
BASE_PATH=/pymalloy/ pnpm docs:build
BASE_PATH=/pymalloy/ pnpm docs:preview
```

Run `actionlint .github/workflows/*.yml` after workflow changes.
