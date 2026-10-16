"""Serve JupyterLite with the release wheel in its browser Python kernel."""

from __future__ import annotations

import functools
import json
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from tempfile import TemporaryDirectory

import nbformat
from fixtures.model import SALES, SOURCE
from pyodide_support import StaticServer, bootstrap, runtime_config


def main() -> None:
    with TemporaryDirectory(prefix="pymalloy-jupyterlite-") as directory:
        root = Path(directory)
        contents = root / "files"
        contents.mkdir()
        cells = [
            bootstrap(),
            f"""from IPython.display import display
source = {SOURCE!r}
widget = pm.MalloyWidget(source, files={{"sales.csv": {SALES!r}}}, query="sales.by_region", runtime=runtime)
display(widget)""",
            """print("Python received:", json.dumps(to_dict(widget.state)["rows"]))""",
            """widget.givens = {"region_filter": "South"}
widget.query = "sales.filtered"
print("South selected")""",
            """print("Python filtered:", json.dumps(to_dict(widget.state)["rows"]))""",
            """print("Browser selected:", widget.query)""",
            """widget.close()
print("Analysis closed")""",
        ]
        notebook = nbformat.v4.new_notebook(
            cells=[nbformat.v4.new_code_cell(source) for source in cells],
            metadata={
                "kernelspec": {
                    "display_name": "Python (Pyodide)",
                    "language": "python",
                    "name": "python",
                }
            },
        )
        nbformat.write(notebook, contents / "sales.ipynb")
        (root / "jupyter-lite.json").write_text(
            json.dumps(
                {
                    "jupyter-config-data": {
                        "litePluginSettings": {
                            "@jupyterlite/pyodide-kernel-extension:kernel": {
                                "pyodideUrl": str(runtime_config()["indexURL"])
                                + "pyodide.mjs"
                            }
                        },
                        "settingsOverrides": {
                            "@jupyterlab/notebook-extension:tracker": {
                                "windowingMode": "none"
                            }
                        },
                        "disabledExtensions": [
                            "@jupyterlab/debugger-extension",
                            "@jupyterlab/notebook-extension:language-server",
                            "@jupyterlab/fileeditor-extension:language-server",
                        ],
                    }
                }
            )
        )
        output = root / "site"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "jupyter",
                "lite",
                "build",
                "--lite-dir",
                str(root),
                "--output-dir",
                str(output),
                "--contents",
                str(contents),
            ],
            capture_output=True,
            cwd=root,
            text=True,
            check=False,
            timeout=90,
        )
        if completed.returncode:
            raise RuntimeError(completed.stdout + completed.stderr)
        handler = functools.partial(SimpleHTTPRequestHandler, directory=str(output))
        with StaticServer(("127.0.0.1", 28445), handler) as server:
            server.serve_forever()


if __name__ == "__main__":
    main()
