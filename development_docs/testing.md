# Testing and compatibility

Test observable contracts through public APIs, files, kernels, and browser state.
The [contributor workflow](README.md#validate-a-change) owns the complete command list.

## Choose tests by contract

| Contract                                                | Focused evidence                                                  | Consumer gate                      |
| ------------------------------------------------------- | ----------------------------------------------------------------- | ---------------------------------- |
| Compiler jobs, imports, document order, query schemas   | `packages/core/tests`, Python tooling/document tests              | `pixi run --locked test`           |
| Source/View authoring, scoped edits, exact saves        | `test_source_view.py`, `test_authoring.py`, `test_persistence.py` | Python suite and roundtrip checker |
| Connection ownership, deadlines, current data           | `test_connection.py`, `test_runtime.py`, `test_execution.py`      | Python and Node suites             |
| Native job generations and cancellation                 | Rust ownership tests in `packages/python/rust/worker.rs`          | `pixi run --locked test-rust`      |
| Exact integers, nested values, temporal data            | `test_result.py`, DuckDB and Node tests                           | Browser numeric readback           |
| Browser Python ownership, async queries, file snapshots | Browser Python tests and `pyodide.spec.ts`                        | Installed browser-wheel acceptance |
| Captured inputs, snapshots, relocated bundles           | `test_data_inputs.py`, `test_source_bundle.py`                    | Installed bundle replay            |
| README, guide, docstring, installed skill examples      | `test_docs_examples.py`, `test_docstrings.py`, `test_agent.py`    | Python suite                       |
| Widget revisions, immutable state, view lifetime        | `test_widget.py`, widget lifecycle tests                          | `pixi run --locked browser`        |
| Installed wheel, exported notebook, CLI process         | `packages/python/tests/e2e`                                       | `pixi run --locked test-installed` |
| Release versions, tags, and distribution inventory      | `test_release.py`, installed wheel probes                         | Source checks and wheel targets    |
| Published TypeScript exports and runtime identity       | `scripts/consumer-canary.ts`                                      | `pixi run --locked canary`         |

`pixi run --locked test-js` covers compiler, Node, DuckDB conversion, widget
lifecycle, and embedded compiler sessions. The normal Python suite deselects
`e2e` tests. The explicit e2e suite builds and installs distributions, executes
notebook processes, and invokes the CLI. Build assets first.

## Python lower bounds

`pixi run --locked floors` runs `scripts/test_python_floors.py` in the default
Python 3.12 environment. It builds a native wheel, creates a temporary
installation with each runtime dependency at its declared lower bound, and runs
the Python suite against that installation. Keep lower-bound testing separate
from the workspace environment resolved by `uv.lock`.

## Browser tests

[Playwright](https://playwright.dev/) drives the browser acceptance suite. Build
runtime assets, the native wheel for the notebook kernels, and the explicit
browser wheel for Pyodide using the
[distribution build commands](releasing.md#browser-wheel). The standalone server
selects `dist/browser/pymalloy-*-py3-none-any.whl`. Then run
`pixi run --locked install-browser` and `pixi run --locked browser`.
Pixi supplies Chromium's Linux shared libraries and points the dynamic linker and
font configuration at the locked environment. The browser executable is
selected by the Playwright version in `pnpm-lock.yaml`.
[Host prerequisites](README.md#host-prerequisites) describe the supported
operating systems and SDK setup.
The configured notebook hosts are:

| Host               | Port  | Contract                                                        |
| ------------------ | ----- | --------------------------------------------------------------- |
| marimo             | 28441 | Handwritten reactive notebook and Python readback               |
| JupyterLab         | 28442 | Kernel communication, multiple views, recovery, close           |
| Standalone Pyodide | 28443 | Browser wheel in browser Python and direct browser runtime      |
| Exported marimo    | 28444 | CLI-generated widget notebook                                   |
| JupyterLite        | 28445 | Browser Python kernel, real widget manager, bidirectional state |
| marimo WebAssembly | 28446 | Exported browser notebook, widget state, reactive inputs        |

[marimo](https://docs.marimo.io/) is a reactive Python notebook editor.
[JupyterLab](https://jupyterlab.readthedocs.io/) hosts notebook kernels and widgets.
[Pyodide](https://pyodide.org/en/stable/) runs Python in the browser.
[JupyterLite](https://jupyterlite.readthedocs.io/), a browser-hosted Jupyter
application, uses its Pyodide kernel. The marimo WebAssembly test exports a
notebook that runs Python in the browser. These tests exercise the hosts' widget
managers, asynchronous Python queries, and Python state readback.
Browser runtime assets and Python packages require network access.

Tests run serially in Chromium. Screenshots and traces are in
`apps/e2e/playwright-report` and `apps/e2e/test-results`.
Native-kernel servers use `uv run --no-sync` to retain the selected installation.
JupyterLite and marimo WebAssembly builders use an isolated, locked
`notebook-hosts` environment and install the browser wheel inside their kernels.
For native wheel coverage, install the built wheel immediately before the
browser suite, then restore the editable workspace with
`pixi run --locked install`.
`PYMALLOY_KERNEL_PYTHON` selects a separate native-wheel Jupyter interpreter.
Install the wheel and ipykernel there for captured inputs and kernel communication.

`pixi run --locked canary` creates a temporary packed-package consumer. It
checks declarations under NodeNext and Bundler resolution, executes native exact-value queries, and
builds a browser bundle for the browser acceptance test. The standalone server
reads that bundle from `PYMALLOY_BROWSER_BUNDLE`.

## Pin the browser Python runtime

`apps/e2e/pyodide/runtime.json` assigns an explicit runtime to each notebook host.
Standalone Pyodide and JupyterLite use 314.0.7. marimo 0.25.1 uses its compatible
314.0.0 loader. Each runtime records its Python version,
[WebAssembly binary interface](https://pyodide.org/en/stable/development/abi.html),
runtime-file SHA-256 digests, direct Python dependency versions, and dependency
lock path. The `pylock.VERSION.json` files beside it record the resolved
packages in Pyodide's lockfile format, including wheel URLs and SHA-256 digests.
All hosts install the same browser wheel URL and verify its hash.

Check the lock offline:

```sh
pixi run --locked uv run --isolated --frozen --only-group release python apps/e2e/pyodide/lock.py --check
```

After changing the runtime or dependency pins, regenerate it with the pinned
runtime's package resolver, then test the browser wheel:

```sh
pixi run --locked uv run --isolated --frozen --only-group release python apps/e2e/pyodide/lock.py
pixi run --locked browser --project pyodide --project jupyterlite --project marimo-wasm
```

Lock generation downloads and verifies the pinned runtime, resolves dependencies
inside WebAssembly, and records their artifact identities. The browser tests
install the release artifact on a separate consumer job. Build the browser wheel
before running them locally. The JupyterLite launcher resolves its scoped
`notebook-hosts` dependency group in an isolated environment automatically.

## Check upstream samples

Use an existing [Malloy samples](https://github.com/malloydata/malloy-samples)
checkout and prepared data. The sample checker command is
`pixi run --locked uv run --frozen python packages/python/tests/check_samples.py CHECKOUT --data-root DATA
--output /tmp/sample-results --runtime`.

`results.json` records the sample revision and per-source outcomes. It checks
deterministic exports, executes marimo/Jupyter notebooks, and compares each query
with native SQL. `--runtime` includes `Query.run`. Missing data and incompatible
samples return nonzero. `--execute-writes` enables COPY and requires isolated data
with output destinations prepared.

The roundtrip command is
`pixi run --locked uv run --frozen python packages/python/tests/check_roundtrip.py CHECKOUT --data-root DATA
--output /tmp/roundtrip-results`.
It parses models, emits and executes Python, and recompiles captured imports.
A query needs equivalent SQL or DuckDB syntax trees plus matching typed results.
Matching rows on one dataset alone cannot prove semantic equivalence.
Reports retain hashes, SQL comparison, types, row counts, outcomes, and generated
Python. Inspect skipped writes and timeouts before interpreting corpus coverage.

Both checkers preserve row and nested-list order and exact floats by default.
`--unordered` compares top-level row multisets. `--float-precision 9` rounds
floats to nine significant digits. The report records these policies.
The roundtrip checker's SQL-equivalence gate remains in force.

## Measure authoring and dataframe costs

Run benchmarks separately from builds and tests:

```sh
pixi run --locked uv run --frozen python scripts/benchmark_authoring.py --samples 7 --output /tmp/authoring-timings.json
pixi run --locked uv run --frozen python scripts/benchmark_data_inputs.py --rows 1000000 --samples 7 --output /tmp/dataframe-timings.json
pixi run --locked pnpm bench:compiler --samples 7 --output /tmp/compiler-timings.json
pixi run --locked uv run --frozen python scripts/benchmark_notebook.py --samples 7 --output /tmp/notebook-timings.json
```

Record dependency versions, machine, workload, and every sample. Compare medians
under the same environment. Authoring measures construction, compiler startup,
and execution costs. Data capture measures Arrow layouts, verified Parquet, and reference-heavy
bundles. Compiler measurements use synthetic schemas and exclude database execution
and startup. Notebook measurements cover display, state publication, and Arrow
preview serialization. Python allocation measurements exclude existing objects and
native Arrow buffers. Keep timing thresholds out of behavior tests.
