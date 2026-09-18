from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from pymalloy._document import Document, Markdown, Profile, Query
from pymalloy.export._python import (
    connection_setup,
    data_setup,
    files_setup,
    givens_setup,
    model_setup,
    model_source_setup,
    query_title,
    query_variables,
    widget_setup,
)


@dataclass(frozen=True)
class Code:
    source: str
    after: str | None = None


@dataclass(frozen=True)
class SQL:
    name: str
    sql: str
    after: str | None = None


@dataclass(frozen=True)
class Notebook:
    dependencies: tuple[str, ...]
    cells: tuple[Markdown | Code | SQL, ...]


def _precompiled(query: Query, name: str, after: str | None) -> Code | SQL:
    if query.kind == "select":
        return SQL(name, query.sql, after)
    return Code(
        "with connect() as _connection:\n"
        f"    _ = _connection.execute({query.sql!r})\n"
        f"{name} = pl.DataFrame()\n{name}",
        after,
    )


def _server(query: Query, name: str, after: str | None) -> Code:
    if query.kind == "copy":
        source = f"_ = model.connection.execute({query.sql!r})\n{name} = pl.DataFrame()"
    else:
        source = f"{name} = model.query({query.name!r}).run(givens=givens).polars()"
    return Code(f"{source}\n{name}", after)


def _widget(query: Query, name: str, after: str | None) -> Code:
    return Code(widget_setup(name, query.name), after)


def plan(
    document: Document, output_path: str | Path, *, base: str, imports: str
) -> Notebook:
    """Resolve execution policy once; serializers supply notebook syntax only."""
    queries: Callable[[Query, str, str | None], Code | SQL]
    match document.profile:
        case Profile.PRECOMPILED:
            requirements = ("duckdb>=1.5", "polars>=1.44")
            runtime_imports = "from contextlib import contextmanager\n\nimport duckdb\nimport polars as pl"
            description = (
                "## Data access\n\nEach query opens a connection using this data directory "
                "and closes it after reading its result."
            )
            setup = [connection_setup(document, output_path, base)]
            queries = _precompiled
        case Profile.SERVER:
            requirements = (f"pymalloy[server,dataframes]=={version('pymalloy')}",)
            runtime_imports = "import pymalloy as pm\nfrom pymalloy import ModelSource\nimport polars as pl"
            description = (
                "## Malloy model\n\n"
                "Edit `model_source` to change the model or its captured imports. "
                "Edit `givens` to change query inputs. Query cells compile and execute "
                "against the current data through `model.query().run()`. "
                "Use `model.queries` to discover queries or pass new Malloy query text "
                "to `model.query().run()`. Call `model.close()` to release resources early."
            )
            setup = [
                data_setup(document, output_path, base),
                model_source_setup(document),
                givens_setup(document),
                model_setup(document),
            ]
            queries = _server
        case Profile.WIDGET:
            requirements = (f"pymalloy=={version('pymalloy')}",)
            runtime_imports = "from pymalloy import MalloyWidget, ModelSource"
            description = (
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
            setup = [
                files_setup(document, output_path, base),
                model_source_setup(document),
                givens_setup(document),
            ]
            queries = _widget
    description += (
        "\n\nInstall the notebook dependencies with `pip install "
        + " ".join(f"'{requirement}'" for requirement in requirements)
        + "`."
    )
    contents = list(document.cells)
    intro = Markdown("# " + document.title)
    if contents and isinstance(contents[0], Markdown):
        intro = contents[0]
        del contents[0]
    cells: list[Markdown | Code | SQL] = [
        intro,
        Code(imports + "\n\n" + runtime_imports),
        Markdown(description),
        *(Code(source) for source in setup),
    ]
    names = iter(query_variables(document))
    writer = None
    for cell in contents:
        if isinstance(cell, Markdown):
            if cell.text.strip():
                cells.append(cell)
            continue
        if not isinstance(cells[-1], Markdown) or not cell.name.startswith(
            ("run:", "sql:")
        ):
            cells.append(Markdown("## " + query_title(cell.name)))
        name = next(names)
        cells.append(queries(cell, name, writer))
        if cell.kind == "copy":
            writer = name
    if document.profile == Profile.WIDGET and not document.queries:
        cells.append(Code(widget_setup("widget")))
    return Notebook(requirements, tuple(cells))
