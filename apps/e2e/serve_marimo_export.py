"""Serve the widget notebook produced by pymalloy export."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from fixtures.model import SALES, SOURCE


def _with_region_control(source: str) -> str:
    match = re.search(r"(\w+) = MalloyWidget\(", source)
    if match is None:
        raise SystemExit("exported notebook has no MalloyWidget assignment")
    name = match.group(1)
    suffix = 'if __name__ == "__main__":\n    app.run()\n'
    if not source.endswith(suffix):
        raise SystemExit("exported notebook does not end with the main guard")
    control = f"""@app.cell
def _(mo):
    region = mo.ui.dropdown(["North", "South"], value="North", label="Region")
    region
    return (region,)


@app.cell
def _({name}, region):
    {name}.givens = {{"region_filter": region.value}}
    return
"""
    return source[: -len(suffix)] + control + "\n\n\n" + suffix


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="pymalloy-marimo-export-"))
    (root / "sales.csv").write_text(SALES)
    model = root / "sales.malloy"
    model.write_text(SOURCE)
    output = root / "analysis.py"
    completed = subprocess.run(
        [
            "pymalloy",
            "export",
            str(model),
            "--format",
            "marimo",
            "--profile",
            "widget",
            "--query",
            "sales.by_region",
            "-o",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr or completed.stdout)
    output.write_text(_with_region_control(output.read_text()))
    model.unlink()
    os.execvp(
        sys.executable,
        [
            sys.executable,
            "-m",
            "marimo",
            "run",
            str(output),
            "--headless",
            "--host",
            "127.0.0.1",
            "--port",
            "28444",
            "--no-token",
            "--session-ttl",
            "0",
        ],
    )


if __name__ == "__main__":
    main()
