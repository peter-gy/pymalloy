"""Serve an isolated JupyterLab workspace for widget integration tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import nbformat
from fixtures.model import SALES, SOURCE, UPDATED_SALES
from jupyterlab.handlers.announcements import NeverCheckForUpdate
from jupyterlab.labapp import LabApp

from pymalloy.exports import compile_document, jupyter

CELLS = [
    f"""import asyncio
import json
from IPython.display import display
from pymalloy import Malloy

source = {SOURCE!r}
widget = Malloy(source, files={{"sales.csv": {SALES!r}}}, query="sales.by_region")

async def ready(expected_rows):
    event = asyncio.Event()
    def changed(change):
        if widget.state.get("status") == "ready" and widget.state.get("rows") == expected_rows:
            event.set()
    widget.observe(changed, names="state")
    try:
        changed(None)
        await asyncio.wait_for(event.wait(), timeout=30)
        return widget.state
    finally:
        widget.unobserve(changed, names="state")

display(widget)""",
    """state = await ready([{"region": "North", "revenue": 42}, {"region": "South", "revenue": 30}])
print("Python rows:", json.dumps(state["rows"], sort_keys=True))""",
    """widget.givens = {"region_filter": "South"}
widget.query = "sales.filtered"
print("South selected in Python")""",
    """state = await ready([{"revenue": 30}])
print("Python filtered:", json.dumps(state["rows"], sort_keys=True))""",
    """widget.query = "sales.by_region"
display(widget)""",
    """print("Browser selected:", widget.query)""",
    """widget.source = "run: missing_source"
print("Invalid model supplied")""",
    f"""widget.files = {{"sales.csv": {UPDATED_SALES.encode()!r}}}
widget.source = source
widget.query = "sales.by_region"
print("Model and data replaced")""",
    """state = await ready([{"region": "North", "revenue": 70}, {"region": "South", "revenue": 10}])
print("Python replacement:", json.dumps(state["rows"], sort_keys=True))""",
    """widget.close()
print("Analysis closed")""",
]


def main() -> None:
    with TemporaryDirectory(prefix="pymalloy-jupyter-") as directory:
        root = Path(directory)
        kernel = root / "data" / "kernels" / "pymalloy"
        kernel.mkdir(parents=True)
        (kernel / "kernel.json").write_text(
            json.dumps(
                {
                    "argv": [
                        sys.executable,
                        "-m",
                        "ipykernel_launcher",
                        "-f",
                        "{connection_file}",
                    ],
                    "display_name": "Python 3 (PyMalloy)",
                    "language": "python",
                }
            )
        )
        labconfig = root / "config" / "labconfig"
        labconfig.mkdir(parents=True)
        (labconfig / "page_config.json").write_text(
            json.dumps(
                {
                    "disabledExtensions": {
                        "@jupyterlab/debugger-extension": True,
                        "@jupyterlab/notebook-extension:language-server": True,
                        "@jupyterlab/fileeditor-extension:language-server": True,
                    }
                }
            )
        )
        settings = root / "settings" / "@jupyterlab" / "apputils-extension"
        settings.mkdir(parents=True)
        (settings / "notification.jupyterlab-settings").write_text(
            json.dumps(
                {
                    "fetchNews": "false",
                    "checkForUpdates": False,
                }
            )
        )
        notebook_settings = root / "settings" / "@jupyterlab" / "notebook-extension"
        notebook_settings.mkdir(parents=True)
        (notebook_settings / "tracker.jupyterlab-settings").write_text(
            json.dumps({"windowingMode": "none"})
        )
        notebooks = root / "notebooks"
        notebooks.mkdir()
        notebook = nbformat.v4.new_notebook(
            cells=[nbformat.v4.new_code_cell(source) for source in CELLS],
            metadata={
                "kernelspec": {
                    "display_name": "Python 3 (PyMalloy)",
                    "language": "python",
                    "name": "pymalloy",
                }
            },
        )
        nbformat.write(notebook, notebooks / "sales.ipynb")
        model = root / "report.malloy"
        imported = root / "sales.malloy"
        imported.write_text(SOURCE)
        model.write_text(
            "import 'sales.malloy'\nsource: report is sales\nrun: report -> by_region"
        )
        (root / "sales.csv").write_text(SALES)
        output = notebooks / "exported.ipynb"
        document = compile_document(model, profile="widget", queries=["run:1"])
        exported = nbformat.reads(
            jupyter.render(document, output_path=output), as_version=4
        )
        exported.metadata.kernelspec = notebook.metadata.kernelspec
        exported.cells.extend(
            nbformat.v4.new_code_cell(source)
            for source in [
                'run_1.givens = {"region_filter": "South"}',
                'print("Export query:", run_1.query)',
                'run_1.close()\nprint("Export closed")',
            ]
        )
        nbformat.write(exported, output)
        model.unlink()
        imported.unlink()
        os.environ.update(
            JUPYTER_CONFIG_DIR=str(root / "config"),
            JUPYTER_DATA_DIR=str(root / "data"),
            JUPYTER_RUNTIME_DIR=str(root / "runtime"),
        )
        LabApp.launch_instance(
            check_for_updates_class=NeverCheckForUpdate,
            news_url=None,
            argv=[
                "--no-browser",
                "--ServerApp.ip=127.0.0.1",
                "--ServerApp.port=28442",
                "--ServerApp.port_retries=0",
                "--IdentityProvider.token=",
                f"--ServerApp.root_dir={notebooks}",
                f"--LabApp.user_settings_dir={root / 'settings'}",
                f"--LabApp.workspaces_dir={root / 'workspaces'}",
            ],
        )


if __name__ == "__main__":
    main()
