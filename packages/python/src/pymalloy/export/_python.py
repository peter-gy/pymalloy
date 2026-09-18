import keyword
import os
import pprint
import re
from pathlib import Path

from pymalloy._model import DEFAULT_CONNECTION
from pymalloy._protocol.givens import encode_givens, given_values
from pymalloy.export._document import Document


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


def data_setup(document: Document, output_path: str | Path, base: str) -> str:
    parent = Path(output_path).resolve().parent
    root = Path(os.path.relpath(document.data_root, parent)).as_posix()
    setup = [f"data_root = ({base} / {root!r}).resolve()"]
    if document.database is not None:
        database = Path(os.path.relpath(document.database, parent)).as_posix()
        setup.append(f"database = ({base} / {database!r}).resolve()")
    if document.profile != "widget":
        setup.append(
            file_configuration(
                repr(sorted(document.files)), remote=bool(document.remote_files)
            )
        )
    aliases = [
        alias for alias in sorted(document.files) if not Path(alias).is_absolute()
    ]
    if document.files and document.profile != "widget":
        setup.extend(["", file_guard(repr(aliases)), "", "check_files()"])
    return "\n".join(setup)


def file_configuration(aliases: str, *, remote: bool = False) -> str:
    """Emit native DuckDB settings for declared notebook inputs."""
    return (
        "connection_config = {\n"
        + f"    'allowed_paths': sorted({{value for alias in {aliases} for value in (alias, str(data_root / alias))}}),\n"
        + ("    'allowed_directories': ['http://', 'https://'],\n" if remote else "")
        + "    'enable_external_access': False,\n}"
    )


def file_guard(aliases: str) -> str:
    """Emit a standalone guard for a trusted Python expression yielding file aliases."""
    return "\n".join(
        [
            "def check_files():",
            f"    for _alias in {aliases}:",
            "        _shadow = Path(_alias)",
            "        if _shadow.is_file() and _shadow.resolve() != (data_root / _alias).resolve():",
            '            raise ValueError(f"Relative file {_alias!r} is shadowed by the current directory. Use an absolute file path or run from a directory without that file.")',
        ]
    )


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
            *(["    check_files()"] if document.files else []),
            f"    with duckdb.connect({database_argument}) as connection:",
            '        connection.execute("SET VARIABLE data_root = ?", [data_root.as_posix()])',
            '        connection.execute("SET file_search_path = ?", [data_root.as_posix()])',
            "        connection.execute(\"SET TimeZone = 'UTC'\")",
            *(
                [
                    f"        for _extension in {document.extensions!r}:",
                    "            connection.install_extension(_extension)",
                    "            connection.load_extension(_extension)",
                    '        _ = connection.execute("SELECT count(*) FROM duckdb_secrets()").fetchone()',
                ]
                if document.extensions
                else []
            ),
            "        for _setting, _value in connection_config.items():",
            "            connection.execute(f'SET \"{_setting}\" = ?', [_value])",
            "        yield connection",
        ]
    )
    return "\n".join(setup)


def model_source_setup(document: Document) -> str:
    source = document.source
    if source is None:
        raise ValueError("The server and widget profiles require model source")
    lines = [
        "model_source = ModelSource(",
        f"    url={source.url!r},",
        f"    document_kind={source.document_kind!r},",
        "    text=(",
    ]

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


def widget_setup(
    name: str, query: str | None = None, *, connection_name: str = DEFAULT_CONNECTION
) -> str:
    arguments = f"source=model_source, files=files, givens=givens, connection_name={connection_name!r}"
    if query is not None:
        arguments += f", query={query!r}"
    return f"{name} = MalloyWidget({arguments})\n{name}"


def model_setup(document: Document) -> str:
    arguments = f"data_root=data_root, connection_name={document.connection_name!r}, config=connection_config"
    if document.extensions:
        arguments += f", extensions={document.extensions!r}"
    if document.database is not None:
        arguments += ", database=database, read_only=True"
    return (
        ("check_files()\n" if document.files else "")
        + f"model = pm.model(model_source, {arguments})\n"
        'model.connection.execute("SET VARIABLE data_root = ?", [str(data_root)])'
    )


def query_title(name: str) -> str:
    return name.replace("run:", "Query ").replace("_", " ").replace(".", " / ")
