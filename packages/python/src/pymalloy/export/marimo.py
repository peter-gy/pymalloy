from __future__ import annotations

import json
import textwrap
from pathlib import Path

from pymalloy._document import Document, Markdown
from pymalloy.export._plan import SQL, plan
from pymalloy.export._python import literal
from pymalloy.export._scope import scope


def _markdown(text: str) -> str:
    if "\\" in text or '"""' in text:
        return f"mo.md(text={text!r})"
    return f"mo.md({literal(text)})"


def render(document: Document, *, output_path: str | Path) -> str:
    """Render a Python notebook with data paths relative to `output_path`."""
    notebook = plan(
        document, output_path, base="mo.notebook_dir()", imports="import marimo as mo"
    )
    codes = []
    bindings = []
    references = []
    for cell in notebook.cells:
        if isinstance(cell, Markdown):
            code = _markdown(cell.text)
            defined, used = scope(code)
        else:
            if isinstance(cell, SQL):
                code = (
                    "with connect() as _connection:\n"
                    f"    {cell.name} = mo.sql(\n{textwrap.indent(literal(cell.sql), '        ')},\n"
                    "        engine=_connection,\n    )"
                )
                defined, used = scope(code)
            else:
                code = cell.source
                defined, used = cell.scope
            # File writes require explicit dependencies in marimo's execution graph.
            if cell.after is not None:
                code = f"_ = {cell.after}\n" + code
                used = used | {cell.after}
        codes.append(code)
        bindings.append(defined)
        references.append(used - defined)
    requirements = ["marimo>=0.24.0", *notebook.dependencies]
    header = (
        '# /// script\n# requires-python = ">=3.12"\n'
        f"# dependencies = {json.dumps(requirements)}\n# ///"
    )
    available = set().union(*bindings)
    sections = [header, "import marimo", 'app = marimo.App(width="medium")']
    for code, defined, used in zip(codes, bindings, references, strict=True):
        decorator = (
            "@app.cell(hide_code=True)" if code.startswith("mo.md(") else "@app.cell"
        )
        arguments = ", ".join(sorted(used & available))
        outputs = ", ".join(sorted(defined))
        returned = f"return ({outputs},)" if outputs else "return"
        sections.append(
            f"{decorator}\ndef _({arguments}):\n"
            + textwrap.indent(code + "\n" + returned, "    ")
        )
    sections.append('if __name__ == "__main__":\n    app.run()')
    return "\n\n\n".join(sections) + "\n"
