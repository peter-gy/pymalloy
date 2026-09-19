---
layout: home
hero:
  name: PyMalloy
  text: Author, check, run, and share Malloy models.
  tagline: Compose semantic models in Python, query with DuckDB, and carry models and inputs into notebooks or source bundles.
  actions:
    - theme: brand
      text: Author a model
      link: /guide/authoring
    - theme: alt
      text: Try a browser widget
      link: /guide/getting-started
features:
  - title: Compose with Python
    details: Build symbolic expressions and reusable queries, or edit existing Malloy while preserving surrounding source.
    link: /guide/authoring
  - title: Check assumptions
    details: Combine compiler diagnostics, optional documentation checks, and named counterexample queries.
    link: /guide/authoring#check-and-save-a-revision
  - title: Carry models and inputs
    details: Capture prepared dataframes, bundle Malloy with copied data, or export an executable notebook.
    link: /guide/bundles
---

## Choose where to start

[Run queries from Python](/guide/headless-python) with `pymalloy[headless]`, or
[display a browser widget](/guide/getting-started) with the base `pymalloy`
package. Widgets run Malloy and DuckDB WebAssembly in the browser and require
no Deno or headless extra.

[Choose a workflow](/guide/overview) for authoring, dataframe inputs, validation,
source bundles, notebook export, and the Node and browser JavaScript APIs.
[Concepts and boundaries](/guide/concepts) explains what each step captures and checks.
