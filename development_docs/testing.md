# Testing and compatibility

Test consumer behavior through API results, files, kernels, and browser state.
Use the smallest boundary that proves the contract, then check affected runtimes.

## Choose tests by contract

| Contract                                                     | Primary evidence                                   | Additional boundary                                |
| ------------------------------------------------------------ | -------------------------------------------------- | -------------------------------------------------- |
| Malloy parsing, imports, query selection, and document order | `packages/core/tests`                              | Python tooling and export tests                    |
| Source coordinates, diagnostics, inspection, and formatting  | Core tooling tests and Python `test_tooling.py`    | Widget error recovery in a browser                 |
| Native file resolution and database identifiers              | Node session tests and Python `test_runtime.py`    | Exported notebook execution from another directory |
| Nested values, exact integers, dates, and nulls              | Node/Python result tests and browser Arrow tests   | Pyodide numeric readback                           |
| Model reuse, queued calls, close, and borrowed transactions  | Node session tests and Python runtime tests        | Widget multiple-view and worker lifecycle cases    |
| Input revisions, state snapshots, and trait validation       | Python `test_widget.py` and widget lifecycle tests | marimo, JupyterLab, and Pyodide synchronization    |
| Ordered Markdown/SQL cells and COPY writes                   | Python document, marimo, and Jupyter tests         | Executed notebooks and upstream samples            |
| Bundled assets, optional imports, and distribution contents  | Isolated wheel/source-archive installs             | Browser tests against the installed wheel          |

For lifecycle races, control when work settles and assert which result survives.
Avoid sleeps, private field layouts, and mirrored implementation constants.

`pnpm test` covers core, Node, Arrow conversion, and widget lifecycle. `pytest`
runs `packages/python/tests`, including native processes and exported notebooks.
Build assets and install Python extras first.

## Browser tests

Build the runtime assets and a wheel before starting the browser suite:

```sh
pnpm build
uv sync --frozen --all-packages --all-extras
uv build --package pymalloy
pnpm --filter @pymalloy/e2e install-browser
pnpm e2e
```

The standalone server requires exactly one `pymalloy-*-py3-none-any.whl` in root
`dist/`. Move older wheels aside before running the suite.

Local marimo and JupyterLab tests use the installed Python workspace. To test the
wheel as CI does, install it immediately before `pnpm e2e`:

```sh
uv pip install --no-deps --reinstall-package pymalloy dist/pymalloy-*.whl
pnpm e2e
```

The test servers use `uv run --no-sync` to retain the selected installation.
Run `uv sync --frozen --all-packages --all-extras` to return to the editable
workspace afterward.

Playwright starts and stops three servers defined in
`apps/e2e/playwright.config.ts`:

| Host               | Port  | Boundary exercised                                                                                |
| ------------------ | ----- | ------------------------------------------------------------------------------------------------- |
| marimo             | 28441 | Widget rendering, reactive Python readback, and input updates                                     |
| JupyterLab         | 28442 | Kernel communication, several views of one widget, recovery, and close                            |
| Standalone Pyodide | 28443 | Base-wheel installation in browser Python, binary inputs, precise readback, and browser execution |

Pyodide supplies an anywidget-model adapter to test the packaged frontend against
browser Python. JupyterLab tests the host's widget manager and communication.
Keep both checks when changing synchronization.

Tests run serially in Chromium. Failure screenshots and traces are in
`apps/e2e/playwright-report/` and `apps/e2e/test-results/`. DuckDB workers and
WebAssembly use the configured bundles. Pyodide and Python packages load over
the network.

## Continuous integration

`.github/workflows/ci.yml` starts documentation, static checks, and runtime
artifact production independently:

| Job               | Inputs and result                                                                                 |
| ----------------- | ------------------------------------------------------------------------------------------------- |
| `docs`            | Calls the reusable Pages workflow to build and check the public site                              |
| `check`           | Checks the Python lock, Ruff formatting/lint, Python types, and whitespace                        |
| `build`           | Builds runtime packages and Python distributions, checks metadata, and uploads shared artifacts   |
| `test-javascript` | Downloads built packages, runs `pnpm check` including Oxlint and Knip, then JavaScript tests      |
| `test-python`     | Downloads staged Python assets and runs pytest on Python 3.12, 3.13, and 3.14                     |
| `package`         | Downloads distributions, rebuilds a wheel from the source archive, and verifies isolated installs |
| `e2e`             | Downloads distributions and assets, installs the built wheel, and tests all three browser hosts   |
| `required`        | Fails unless every prerequisite job succeeds                                                      |

Four test jobs consume `build` artifacts. Static checks use
`--no-install-workspace` to run before Python assets exist. JavaScript typechecks,
type-aware lint, and Knip run after package declarations are built.

CI builds docs separately from runtime packages. Local `pnpm build` builds the
whole workspace. Pages deploys on `main` and contributes to the required gate.
Pull requests and release tags build docs without deploying.

Use `required` for branch protection. CI covers the Python version matrix on
Ubuntu with Chromium. Test other affected platforms when changing paths,
processes, or workers.

## Check upstream samples

Use an existing Malloy samples checkout and a prepared data directory:

```sh
uv run python packages/python/tests/check_samples.py /path/to/malloy-samples \
  --data-root /path/to/data --output /tmp/sample-results --runtime
```

`results.json` records the checkout revision and per-source outcomes. The checker
verifies deterministic exports, executes marimo and Jupyter notebooks, and
compares results by query selector against native-model SQL. `--runtime` also
compares `Model.run()`. Each query records which consumers passed.

Comparisons preserve column names, row and nested-list order, and exact floats.
`--unordered` compares top-level rows as a multiset, preserving duplicates and
nested-list order. `--float-precision 9` rounds floats to nine significant digits.
The report records both options. Unseeded sampling checks columns and successful
execution because rows can differ between runs.

Missing data and incompatible samples return a nonzero exit status. Per-source
results distinguish missing data from compiler or runtime failures.
`--execute-writes` enables COPY and requires an isolated data directory containing
its output destinations.
