from __future__ import annotations

import json
import textwrap
from pathlib import Path

from pymalloy._document import Document, Markdown
from pymalloy.exports._python import (
    connection_setup,
    dependencies,
    files_setup,
    givens_setup,
    literal,
    model_setup,
    model_source_setup,
    query_title,
    query_variables,
    runtime_description,
    runtime_imports,
    widget_setup,
)


def render(document: Document, *, output_path: str | Path) -> str:
    """Render notebook JSON with data paths relative to `output_path`.

    Execute the kernel from the exported notebook's directory. Query cells
    display widgets or materialize Polars dataframes according to the profile.
    Native and precompiled COPY cells write their destinations.
    """
    contents = list(document.cells)
    intro = "# " + document.title
    if contents and isinstance(contents[0], Markdown):
        intro = contents[0].text
        contents.pop(0)
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

    append("markdown", intro)
    append(
        "code",
        "from pathlib import Path\n\n" + runtime_imports(document),
    )
    append(
        "markdown",
        runtime_description(document)
        + "\n\nInstall the kernel dependencies with `pip install "
        + " ".join(f"'{requirement}'" for requirement in dependencies(document))
        + "`.",
    )
    if document.profile == "widget":
        append("code", files_setup(document, output_path, "Path.cwd()"))
    else:
        append("code", connection_setup(document, output_path, "Path.cwd()"))
    if document.profile != "precompiled":
        append("code", model_source_setup(document))
        append("code", givens_setup(document))
    if document.profile == "native":
        append("code", model_setup(document))
    names = iter(query_variables(document))
    for cell in contents:
        if isinstance(cell, Markdown):
            if cell.text.strip():
                append("markdown", cell.text)
            continue
        if cells[-1]["cell_type"] != "markdown" or not cell.name.startswith(
            ("run:", "sql:")
        ):
            append("markdown", "## " + query_title(cell.name))
        name = next(names)
        if document.profile == "widget":
            append("code", widget_setup(name, cell.name))
            continue
        if document.profile == "native":
            append(
                "code",
                f"{name} = model.run(query={cell.name!r}, givens=givens)\n{name}",
            )
            continue
        execute = (
            f"_connection.execute(\n{textwrap.indent(literal(cell.sql), '    ')}\n)"
        )
        if cell.kind == "copy":
            code = f"_ = {execute}\n{name} = pl.DataFrame()"
        else:
            code = (
                f"{name} = pl.DataFrame(\n    _connection.sql(\n"
                f"{textwrap.indent(literal(cell.sql), '        ')}\n    )\n)"
            )
        append(
            "code",
            "with connect() as _connection:\n"
            + textwrap.indent(code, "    ")
            + f"\n{name}",
        )
    if document.profile == "widget" and not document.queries:
        append("code", widget_setup("widget"))
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
                        "dependencies": dependencies(document),
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
