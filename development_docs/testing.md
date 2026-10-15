# Testing and compatibility

Test observable contracts through public APIs, files, kernels, and browser state.
The [contributor workflow](README.md#validate-a-change) owns the complete command list.

## Choose tests by contract

| Contract                                              | Focused evidence                                                  | Consumer gate                            |
| ----------------------------------------------------- | ----------------------------------------------------------------- | ---------------------------------------- |
| Compiler jobs, imports, document order, query schemas | `packages/core/tests`, Python tooling/document tests              | `pnpm test`, `uv run --frozen pytest -q` |
| Source/View authoring, scoped edits, exact saves      | `test_source_view.py`, `test_authoring.py`, `test_persistence.py` | Python suite and roundtrip checker       |
| Connection ownership, deadlines, current data         | `test_connection.py`, `test_runtime.py`, `test_execution.py`      | Python and Node suites                   |
| Exact integers, nested values, temporal data          | `test_result.py`, DuckDB and Node tests                           | Browser numeric readback                 |
| Captured inputs, snapshots, relocated bundles         | `test_data_inputs.py`, `test_source_bundle.py`                    | Installed bundle replay                  |
| README, guide, docstring, installed skill examples    | `test_docs_examples.py`, `test_docstrings.py`, `test_agent.py`    | Python suite                             |
| Widget revisions, immutable state, view lifetime      | `test_widget.py`, widget lifecycle tests                          | `pnpm e2e`                               |
| Installed wheel, exported notebook, CLI process       | `packages/python/tests/e2e`                                       | `uv run --frozen pytest -m e2e -q`       |
| Published TypeScript exports and runtime identity     | `scripts/consumer-canary.ts`                                      | `pnpm canary`                            |

`pnpm test` covers compiler, Node, DuckDB conversion, widget lifecycle, and the
compiler service. The normal Python suite deselects `e2e` tests. The explicit e2e
suite builds and installs distributions, executes notebook processes, and invokes
the CLI. Build assets first.

## Browser tests

[Playwright](https://playwright.dev/) drives the browser acceptance suite. Build
runtime assets and exactly one root `dist/pymalloy-*-py3-none-any.whl`, then run
`pnpm --filter @pymalloy/e2e install-browser` and `pnpm e2e`.
The four configured hosts are:

| Host               | Port  | Contract                                                |
| ------------------ | ----- | ------------------------------------------------------- |
| marimo             | 28441 | Handwritten reactive notebook and Python readback       |
| JupyterLab         | 28442 | Kernel communication, multiple views, recovery, close   |
| Standalone Pyodide | 28443 | Base wheel in browser Python and direct browser runtime |
| Exported marimo    | 28444 | CLI-generated widget notebook                           |

[marimo](https://docs.marimo.io/) is a reactive Python notebook editor.
[JupyterLab](https://jupyterlab.readthedocs.io/) hosts notebook kernels and widgets.
[Pyodide](https://pyodide.org/en/stable/) runs Python in the browser. Its bootstrap
loads `micropip` and `lzma` before installing the wheel. Browser runtime assets
and Python packages require network access.

Tests run serially in Chromium. Screenshots and traces are in
`apps/e2e/playwright-report` and `apps/e2e/test-results`.
Servers use `uv run --no-sync` to retain the selected installation. For wheel
coverage, install the built wheel immediately before the browser suite and restore
the editable workspace with the setup sync command afterward.
`PYMALLOY_KERNEL_PYTHON` selects a separate base-package Jupyter interpreter.
Install PyArrow and ipykernel there for captured inputs and kernel communication.

`pnpm canary` creates a temporary packed-package consumer. It checks declarations
under NodeNext and Bundler resolution, executes native exact-value queries, and
builds a browser bundle for the browser acceptance test. The standalone server
reads that bundle from `PYMALLOY_BROWSER_BUNDLE`.

## Check upstream samples

Use an existing [Malloy samples](https://github.com/malloydata/malloy-samples)
checkout and prepared data. The sample checker command is
`uv run python packages/python/tests/check_samples.py CHECKOUT --data-root DATA
--output /tmp/sample-results --runtime`.

`results.json` records the sample revision and per-source outcomes. It checks
deterministic exports, executes marimo/Jupyter notebooks, and compares each query
with native SQL. `--runtime` includes `Query.run`. Missing data and incompatible
samples return nonzero. `--execute-writes` enables COPY and requires isolated data
with output destinations prepared.

The roundtrip command is
`uv run python packages/python/tests/check_roundtrip.py CHECKOUT --data-root DATA
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
uv run python scripts/benchmark_authoring.py --samples 7 --output /tmp/authoring-timings.json
uv run python scripts/benchmark_data_inputs.py --rows 1000000 --samples 7 --output /tmp/dataframe-timings.json
pnpm bench:compiler --samples 7 --output /tmp/compiler-timings.json
uv run python scripts/benchmark_notebook.py --samples 7 --output /tmp/notebook-timings.json
```

Record dependency versions, machine, workload, and every sample. Compare medians
under the same environment. Authoring measures construction, process, and execution
costs. Data capture measures Arrow layouts, verified Parquet, and reference-heavy
bundles. Compiler measurements use synthetic schemas and exclude database execution
and startup. Notebook measurements cover display, state publication, and Arrow
preview serialization. Python allocation measurements exclude existing objects and
native Arrow buffers. Keep timing thresholds out of behavior tests.
