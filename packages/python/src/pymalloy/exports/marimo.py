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


def _markdown(text: str) -> str:
    # The notebook serializer normalizes positional Markdown string escapes.
    if "\\" in text or '"""' in text:
        return f"mo.md(text={text!r})"
    return f"mo.md({literal(text)})"


def render(document: Document, *, output_path: str | Path) -> str:
    """Render a Python notebook with data paths relative to `output_path`."""
    try:
        from marimo._ast.app_config import _AppConfig
        from marimo._ast.cell import CellConfig
        from marimo._ast.codegen import generate_filecontents
    except ModuleNotFoundError as error:
        if error.name != "marimo":
            raise
        raise ImportError("Marimo export requires pymalloy[marimo]") from error
    cells = list(document.cells)
    intro = "# " + document.title
    if cells and isinstance(cells[0], Markdown):
        intro = cells[0].text
        cells.pop(0)
    codes = [
        _markdown(intro),
        "import marimo as mo\n\n" + runtime_imports(document),
        _markdown(runtime_description(document)),
    ]
    if document.profile == "widget":
        codes.append(files_setup(document, output_path, "mo.notebook_dir()"))
    else:
        codes.append(connection_setup(document, output_path, "mo.notebook_dir()"))
    if document.profile != "precompiled":
        codes.extend(
            [
                model_source_setup(document),
                givens_setup(document),
            ]
        )
    if document.profile == "native":
        codes.append(model_setup(document))
    names = iter(query_variables(document))
    writer = None
    for cell in cells:
        if isinstance(cell, Markdown):
            if cell.text.strip():
                codes.append(_markdown(cell.text))
            continue
        query = cell
        if not codes[-1].startswith("mo.md(") or not query.name.startswith(
            ("run:", "sql:")
        ):
            codes.append(_markdown("## " + query_title(query.name)))
        name = next(names)
        if document.profile == "widget":
            code = widget_setup(name, query.name)
        elif document.profile == "native":
            code = f"{name} = model.run(query={query.name!r}, givens=givens)\n{name}"
        elif query.kind == "copy":
            code = (
                "with connect() as _connection:\n"
                "    _ = _connection.execute(\n"
                f"{textwrap.indent(literal(query.sql), '        ')}\n    )\n"
                f"{name} = pl.DataFrame()"
            )
        else:
            code = (
                "with connect() as _connection:\n"
                f"    {name} = mo.sql(\n{textwrap.indent(literal(query.sql), '        ')},\n"
                "        engine=_connection,\n    )"
            )
        # File writes need a Python dependency because marimo excludes file
        # references from its SQL dependency graph.
        if writer:
            code = f"_ = {writer}\n" + code
        codes.append(code)
        if query.kind == "copy":
            writer = name
    if document.profile == "widget" and not document.queries:
        codes.append(widget_setup("widget"))
    requirements = ["marimo>=0.24.0", *dependencies(document)]
    header = (
        '# /// script\n# requires-python = ">=3.12"\n'
        f"# dependencies = {json.dumps(requirements)}\n# ///"
    )
    return generate_filecontents(
        codes=codes,
        names=["_"] * len(codes),
        cell_configs=[
            CellConfig(hide_code=code.startswith("mo.md(")) for code in codes
        ],
        config=_AppConfig(width="medium"),
        header_comments=header,
    )
