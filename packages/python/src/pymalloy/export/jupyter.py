from __future__ import annotations

import json
import textwrap
from pathlib import Path

from pymalloy.export._document import Document, Markdown
from pymalloy.export._plan import SQL, plan
from pymalloy.export._python import literal


def render(document: Document, *, output_path: str | Path) -> str:
    """Render notebook JSON with data paths relative to `output_path`.

    Execute the kernel from the exported notebook's directory. Query cells
    display widgets or materialize Polars dataframes according to the profile.
    Server and precompiled COPY cells write their destinations.
    """
    notebook = plan(
        document, output_path, base="Path.cwd()", imports="from pathlib import Path"
    )
    cells = []

    def append(kind: str, source: str) -> None:
        cell = {
            "cell_type": kind,
            "id": f"cell-{len(cells) + 1:04d}",
            "metadata": {},
            "source": source,
        }
        if kind == "code":
            cell.update(execution_count=None, outputs=[])
        cells.append(cell)

    for cell in notebook.cells:
        if isinstance(cell, Markdown):
            append("markdown", cell.text)
        elif isinstance(cell, SQL):
            code = (
                f"{cell.name} = pl.DataFrame(\n    _connection.sql(\n"
                f"{textwrap.indent(literal(cell.sql), '        ')}\n    )\n)"
            )
            append(
                "code",
                "with connect() as _connection:\n"
                + textwrap.indent(code, "    ")
                + f"\n{cell.name}",
            )
        else:
            append("code", cell.source)
    return (
        json.dumps(
            {
                "cells": cells,
                "metadata": {
                    "kernelspec": {
                        "display_name": "Python 3",
                        "language": "python",
                        "name": "python3",
                    },
                    "language_info": {"name": "python"},
                    "title": document.title,
                    "pymalloy": {
                        "profile": document.profile,
                        "dependencies": notebook.dependencies,
                    },
                },
                "nbformat": 4,
                "nbformat_minor": 5,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
