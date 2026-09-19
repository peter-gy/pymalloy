from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property, partial
from importlib.metadata import version
from pathlib import Path

from pymalloy.export._document import Document, Markdown, Profile, QueryCell
from pymalloy.export._python import (
    connection_setup,
    data_setup,
    files_setup,
    givens_setup,
    model_setup,
    model_source_setup,
    query_title,
    variable,
    widget_setup,
)
from pymalloy.export._scope import scope


@dataclass(frozen=True)
class Code:
    source: str
    after: str | None = None

    @cached_property
    def scope(self) -> tuple[frozenset[str], frozenset[str]]:
        return scope(self.source)


@dataclass(frozen=True)
class SQL:
    name: str
    sql: str
    after: str | None = None


@dataclass(frozen=True)
class Notebook:
    dependencies: tuple[str, ...]
    cells: tuple[Markdown | Code | SQL, ...]
    variables: tuple[str, ...]


def _precompiled(query: QueryCell, name: str, after: str | None) -> Code | SQL:
    if query.kind == "select":
        return SQL(name, query.sql, after)
    return Code(
        "with connect() as _connection:\n"
        f"    _ = _connection.execute({query.sql!r})\n"
        f"{name} = pl.DataFrame()\n{name}",
        after,
    )


def _headless(query: QueryCell, name: str, after: str | None) -> Code:
    if query.kind == "copy":
        source = f"_ = model.connection.execute({query.sql!r})\n{name} = pl.DataFrame()"
    else:
        source = f"{name} = model.query({query.name!r}).run(givens=givens).polars()"
    return Code(f"{source}\n{name}", after)


def _widget(
    query: QueryCell, name: str, after: str | None, *, connection_name: str
) -> Code:
    return Code(widget_setup(name, query.name, connection_name=connection_name), after)


def plan(
    document: Document, output_path: str | Path, *, base: str, imports: str
) -> Notebook:
    """Resolve execution policy once; serializers supply notebook syntax only."""
    queries: Callable[[QueryCell, str, str | None], Code | SQL]
    match document.profile:
        case Profile.PRECOMPILED:
            requirements = ("duckdb>=1.5", "polars>=1.44")
            runtime_imports = "from contextlib import contextmanager\nfrom pathlib import Path\n\nimport duckdb\nimport polars as pl"
            description = (
                "## Data access\n\nEach query opens a connection using this data directory "
                "and closes it after reading its result."
            )
            setup = [connection_setup(document, output_path, base)]
            queries = _precompiled
        case Profile.HEADLESS:
            requirements = (
                f"pymalloy[headless]=={version('pymalloy')}",
                "polars>=1.44",
            )
            runtime_imports = "from pathlib import Path\nimport pymalloy as pm\nfrom pymalloy import ModelSource\nimport polars as pl"
            description = (
                "## Malloy model\n\n"
                "Edit `model_source` to change the model or its captured imports. "
                "Edit `givens` to change query inputs. Query cells compile and execute "
                "against the current data through `model.query().run()`. "
                "Use `model.queries` to discover queries or pass new Malloy query text "
                "to `model.query(malloy=...).run()`. Call `model.close()` to release resources early."
            )
            setup = [
                data_setup(document, output_path, base),
                model_source_setup(document),
                givens_setup(document),
                model_setup(document),
            ]
            queries = _headless
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
            queries = partial(_widget, connection_name=document.connection_name)
    if document.profile != Profile.WIDGET:
        description += (
            "\n\nLocal file access is limited to the notebook's declared inputs and COPY outputs. "
            "When preparing an export, declare local SQL reader files with `files=` "
            "and HTTP(S) readers with `remote_files=`. Remote inputs require network access; "
            "their contents are not frozen by export."
        )
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
    # Reserve both notebook host namespaces so names agree across serializers.
    used = {"mo", "Path"}
    for cell in cells:
        if isinstance(cell, Code):
            definitions, references = cell.scope
            used.update(definitions | references)
    variables = tuple(variable(query.name, used) for query in document.queries)
    names = iter(variables)
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
        query = queries(cell, name, writer)
        if document.files and document.profile == Profile.HEADLESS:
            assert isinstance(query, Code)
            query = Code("check_files()\n" + query.source, query.after)
        cells.append(query)
        if cell.kind == "copy":
            writer = name
    if document.profile == Profile.WIDGET and not document.queries:
        cells.append(
            Code(widget_setup("widget", connection_name=document.connection_name))
        )
    return Notebook(requirements, tuple(cells), variables)


def query_variables(document: Document) -> tuple[str, ...]:
    """Return the same result identifiers used by either notebook serializer."""
    return plan(
        document,
        document.data_root / "notebook.py",
        base="Path.cwd()",
        imports="from pathlib import Path",
    ).variables
