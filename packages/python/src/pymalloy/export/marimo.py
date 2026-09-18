from __future__ import annotations

import json
import textwrap
from pathlib import Path

from pymalloy._document import Document, Markdown
from pymalloy.export._plan import SQL, plan
from pymalloy.export._python import literal


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
    notebook = plan(
        document, output_path, base="mo.notebook_dir()", imports="import marimo as mo"
    )
    codes = []
    for cell in notebook.cells:
        if isinstance(cell, Markdown):
            codes.append(_markdown(cell.text))
            continue
        if isinstance(cell, SQL):
            code = (
                "with connect() as _connection:\n"
                f"    {cell.name} = mo.sql(\n{textwrap.indent(literal(cell.sql), '        ')},\n"
                "        engine=_connection,\n    )"
            )
        else:
            code = cell.source
        # File writes require explicit dependencies in marimo's execution graph.
        if cell.after is not None:
            code = f"_ = {cell.after}\n" + code
        codes.append(code)
    requirements = ["marimo>=0.24.0", *notebook.dependencies]
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
