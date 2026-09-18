import keyword
import os
import pprint
import re
from importlib.metadata import version
from pathlib import Path

from pymalloy._document import Document

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
    "Malloy",
    "ModelSource",
    "Session",
    "model_source",
    "session",
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


def connection_setup(document: Document, output_path: str | Path, base: str) -> str:
    parent = Path(output_path).resolve().parent
    root = Path(os.path.relpath(document.data_root, parent)).as_posix()
    setup = [f"data_root = ({base} / {root!r}).resolve()"]
    database_argument = '":memory:"'
    if document.database is not None:
        database = Path(os.path.relpath(document.database, parent)).as_posix()
        setup.append(f"database = ({base} / {database!r}).resolve()")
        database_argument = "str(database), read_only=True"
    if document.profile == "native":
        return "\n".join(setup)
    setup.extend(
        [
            "",
            "@contextmanager",
            "def connect():",
            f"    with duckdb.connect({database_argument}) as connection:",
            '        connection.execute("SET VARIABLE data_root = ?", [data_root.as_posix()])',
            "        connection.execute(\"SET TimeZone = 'UTC'\")",
            "        yield connection",
        ]
    )
    return "\n".join(setup)


def dependencies(document: Document) -> list[str]:
    if document.profile == "native":
        return [f"pymalloy[server]=={version('pymalloy')}"]
    if document.profile == "widget":
        return [f"pymalloy=={version('pymalloy')}"]
    return ["duckdb>=1.5.5", "polars>=1.44.2"]


def runtime_imports(document: Document) -> str:
    if document.profile == "native":
        return "from pymalloy import ModelSource\nfrom pymalloy.server import Session"
    if document.profile == "widget":
        return "from pymalloy import Malloy, ModelSource"
    return "from contextlib import contextmanager\n\nimport duckdb\nimport polars as pl"


def runtime_description(document: Document) -> str:
    if document.profile == "native":
        return (
            "## Malloy model\n\n"
            "Edit `model_source` to change the model or its captured imports. "
            "Edit `givens` to change query inputs. Query cells compile and execute "
            "against the current data through `model.run()`. "
            "Use `model.queries` to discover queries or pass new Malloy query text "
            "to `model.run()`. Call `session.close()` when finished using the model."
        )
    if document.profile == "widget":
        return (
            "## Interactive Malloy model\n\n"
            "Edit `model_source` to change the model or its captured imports, "
            "and `givens` to change query inputs. Each widget offers the full "
            "model's queries in its selector and runs them in browser DuckDB "
            "WebAssembly. `files` reads local data into the widgets when the "
            "notebook runs. Remote data requires browser network access and "
            "cross-origin resource sharing (CORS) permission from its server. "
            "Its `.state` updates asynchronously "
            "and has status `ready` when results are available. "
            "Call `.close()` on each widget when finished."
        )
    return (
        "## Data access\n\nEach query opens a connection using this data directory "
        "and closes it after reading its result."
    )


def model_source_setup(document: Document) -> str:
    source = document.source
    if source is None:
        raise ValueError("The native and widget profiles require model source")
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
    return "givens = " + pprint.pformat(document.givens, sort_dicts=True)


def files_setup(document: Document, output_path: str | Path, base: str) -> str:
    parent = Path(output_path).resolve().parent
    lines = ["files = {"]
    for alias, path in document._widget_files:
        relative = Path(os.path.relpath(path, parent)).as_posix()
        lines.append(f"    {alias!r}: ({base} / {relative!r}).read_bytes(),")
    lines.append("}")
    return "\n".join(lines)


def widget_setup(name: str, query: str | None = None) -> str:
    arguments = "source=model_source, files=files, givens=givens"
    if query is not None:
        arguments += f", query={query!r}"
    return f"{name} = Malloy({arguments})\n{name}"


def model_setup(document: Document) -> str:
    arguments = "data_root=data_root"
    if document.database is not None:
        arguments += ", database=database, read_only=True"
    return (
        f"session = Session({arguments})\n"
        "try:\n"
        "    model = session.load_source(model_source)\n"
        "except BaseException:\n"
        "    session.close()\n"
        "    raise"
    )


def query_title(name: str) -> str:
    return name.replace("run:", "Query ").replace("_", " ").replace(".", " / ")
