"""Serve a marimo WebAssembly export with the release browser wheel."""

from __future__ import annotations

import asyncio
import functools
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from tempfile import TemporaryDirectory

from fixtures.model import SALES, SOURCE
from marimo._export.file import export_wasm
from marimo._export.requests import WASMFileExportRequest
from marimo._schemas.export_options import WASMExportOptions, WASMRuntimeConfig
from marimo._utils.marimo_path import MarimoPath
from pyodide_support import StaticServer, bootstrap, runtime_config


def main() -> None:
    with TemporaryDirectory(prefix="pymalloy-marimo-wasm-") as directory:
        root = Path(directory)
        notebook = root / "analysis.py"
        setup = "\n".join(
            "    " + line if line else "" for line in bootstrap("marimo").splitlines()
        )
        notebook.write_text(
            f"""import marimo
app = marimo.App(width="medium")

@app.cell
async def _():
    import marimo as mo
{setup}
    return browser, mo, pm, runtime, to_dict

@app.cell
def _(mo):
    region = mo.ui.dropdown(["North", "South"], value="North", label="Region")
    close = mo.ui.checkbox(label="Close analysis")
    mo.hstack([region, close])
    return close, region

@app.cell
async def _(browser, mo, pm, runtime):
    browser_connection = browser.connect(runtime=runtime)
    browser_model = await browser_connection.model({SOURCE!r}, files={{"sales.csv": {SALES.encode()!r}}})
    analysis = mo.ui.anywidget(pm.MalloyWidget(browser_model, query="sales.filtered"))
    analysis
    return analysis, browser_connection

@app.cell
async def _(analysis, browser_connection, close, region):
    if close.value:
        analysis.widget.close()
        await browser_connection.close()
    else:
        analysis.widget.givens = {{"region_filter": region.value}}
    closed = close.value
    return (closed,)

@app.cell
def _(analysis, closed, mo, to_dict):
    _ = analysis.value
    state = to_dict(analysis.widget.state)
    if closed:
        assert state["status"] == "closed"
    mo.md(f"Python received: `{{state.get('status')}}`\\n\\nRows: `{{state.get('rows', [])}}`")
    return

if __name__ == "__main__":
    app.run()
"""
        )
        result = asyncio.run(
            export_wasm(
                WASMFileExportRequest(
                    path=MarimoPath(str(notebook)),
                    options=WASMExportOptions(
                        mode="run",
                        show_code=False,
                        runtime=WASMRuntimeConfig(
                            pyodide_index_url=str(runtime_config("marimo")["indexURL"]),
                        ),
                    ),
                )
            )
        )
        if result.did_error:
            raise RuntimeError("marimo could not export the browser notebook")
        (root / "index.html").write_text(result.contents)
        static = Path(__import__("marimo").__file__).parent / "_static"
        # The export uses marimo's matching frontend assets at their normal paths.
        for asset in static.iterdir():
            if asset.name != "index.html":
                (root / asset.name).symlink_to(
                    asset, target_is_directory=asset.is_dir()
                )
        handler = functools.partial(SimpleHTTPRequestHandler, directory=str(root))
        with StaticServer(("127.0.0.1", 28446), handler) as server:
            server.serve_forever()


if __name__ == "__main__":
    main()
