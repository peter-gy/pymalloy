import keyword
import os
import pprint
import re
from pathlib import Path

from pymalloy._document import Document
from pymalloy._givens import encode_givens, given_values

_RESERVED = {
    "BaseException",
    "Path",
    "mo",
    "duckdb",
    "pl",
    "contextmanager",
    "connect",
    "connection",
    "data_root",
    "database",
    "MalloyWidget",
    "ModelSource",
    "pm",
    "model_source",
    "model",
    "givens",
    "files",
    "str",
}


def literal(text: str) -> str:
    # Escape Python syntax while keeping SQL and Markdown readable in the editor.
    return '"""\n' + text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"') + '\n"""'


def variable(label: str, used: set[str]) -> str:
    base = re.sub(r"[^a-zA-Z0-9_]", "_", label).strip("_") or "result"
    if base[0].isdigit() or keyword.iskeyword(base):
        base = f"result_{base}"
    name = base
    suffix = 2
    while name in used:
        name = f"{base}_{suffix}"
        suffix += 1
    used.add(name)
    return name


def query_variables(document: Document) -> tuple[str, ...]:
    used = set(_RESERVED)
    return tuple(variable(query.name, used) for query in document.queries)


def data_setup(document: Document, output_path: str | Path, base: str) -> str:
    parent = Path(output_path).resolve().parent
    root = Path(os.path.relpath(document.data_root, parent)).as_posix()
    setup = [f"data_root = ({base} / {root!r}).resolve()"]
    if document.database is not None:
        database = Path(os.path.relpath(document.database, parent)).as_posix()
        setup.append(f"database = ({base} / {database!r}).resolve()")
    return "\n".join(setup)


def connection_setup(document: Document, output_path: str | Path, base: str) -> str:
    database_argument = (
        "str(database), read_only=True"
        if document.database is not None
        else '":memory:"'
    )
    setup = [data_setup(document, output_path, base)]
    setup.extend(
        [
            "",
            "@contextmanager",
            "def connect():",
            f"    with duckdb.connect({database_argument}) as connection:",
            '        connection.execute("SET VARIABLE data_root = ?", [data_root.as_posix()])',
            '        connection.execute("SET file_search_path = ?", [data_root.as_posix()])',
            "        connection.execute(\"SET TimeZone = 'UTC'\")",
            "        yield connection",
        ]
    )
    return "\n".join(setup)


def model_source_setup(document: Document) -> str:
    source = document.source
    if source is None:
        raise ValueError("The server and widget profiles require model source")
    lines = ["model_source = ModelSource(", f"    url={source.url!r},", "    text=("]

    def append_text(text: str, indent: str) -> None:
        lines.extend(
            f"{indent}{line!r}" for line in text.splitlines(keepends=True) or [""]
        )

    append_text(source.text, "        ")
    lines.extend(["    ),", "    imports={"])
    for url, text in sorted(source.imports.items()):
        lines.append(f"        {url!r}: (")
        append_text(text, "            ")
        lines.append("        ),")
    lines.extend(["    },", ")"])
    return "\n".join(lines)


def givens_setup(document: Document) -> str:
    return "givens = " + pprint.pformat(
        given_values(encode_givens(document.givens)), sort_dicts=True
    )


def files_setup(document: Document, output_path: str | Path, base: str) -> str:
    parent = Path(output_path).resolve().parent
    lines = ["files = {"]
    for alias, path in sorted(document.files.items()):
        relative = Path(os.path.relpath(path, parent)).as_posix()
        lines.append(f"    {alias!r}: ({base} / {relative!r}).read_bytes(),")
    lines.append("}")
    return "\n".join(lines)


def widget_setup(name: str, query: str | None = None) -> str:
    arguments = "source=model_source, files=files, givens=givens"
    if query is not None:
        arguments += f", query={query!r}"
    return f"{name} = MalloyWidget({arguments})\n{name}"


def model_setup(document: Document) -> str:
    arguments = "data_root=data_root"
    if document.database is not None:
        arguments += ", database=database, read_only=True"
    return (
        f"model = pm.model(model_source, {arguments})\n"
        'model.connection.execute("SET VARIABLE data_root = ?", [str(data_root)])'
    )


def query_title(name: str) -> str:
    return name.replace("run:", "Query ").replace("_", " ").replace(".", " / ")
