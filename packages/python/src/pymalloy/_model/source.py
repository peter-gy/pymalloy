from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal
from urllib.parse import urlsplit

DEFAULT_SOURCE_FILENAME = "model.malloy"
type DocumentKind = Literal["model", "notebook"]


def resolve_document_kind(url: str, kind: DocumentKind | None = None) -> DocumentKind:
    if kind is not None:
        if kind not in {"model", "notebook"}:
            raise ValueError("document_kind must be 'model' or 'notebook'")
        return kind
    return (
        "notebook"
        if Path(urlsplit(url).path).suffix in {".malloynb", ".malloysql"}
        else "model"
    )


def validate_url(url: str) -> None:
    if not isinstance(url, str) or not urlsplit(url).scheme:
        raise ValueError("Model source requires an absolute root URL")


def freeze_imports(imports: Mapping[str, str]) -> Mapping[str, str]:
    if not all(
        isinstance(url, str) and urlsplit(url).scheme and isinstance(source, str)
        for url, source in imports.items()
    ):
        raise ValueError("Model imports must map absolute URLs to source text")
    return MappingProxyType(dict(imports))


@dataclass(frozen=True, init=False)
class ModelSource:
    r"""An immutable snapshot of model text and its imported source files.

    Parameters
    ----------
    url : str
        Absolute root URL, used for source locations and relative import resolution.
    text : str
        Root Malloy model or notebook-document text.
    imports : mapping of str to str, optional
        Imported source text keyed by absolute URL. Defaults to an empty mapping.
        Missing imports fail during compilation instead of falling back to I/O.
    document_kind : {"model", "notebook"}, optional
        Explicit root grammar. Otherwise inferred from the URL extension.

    Notes
    -----
    Constructing the snapshot validates its shape, not the model or import closure.
    It contains no table data, database state or Python dataframe preparation logic.
    Use Model.source to capture resolved imports and export.bundle to copy inputs.

    Examples
    --------
    >>> import pymalloy as pm
    >>> source = pm.ModelSource(
    ...     "memory://tour/report.malloy",
    ...     "import 'base.malloy'\nrun: values -> {select: n}",
    ...     {"memory://tour/base.malloy": "source: values is duckdb.sql('SELECT 42 AS n')"},
    ... )
    >>> pm.run(source).rows()
    [{'n': 42}]
    """

    url: str
    text: str
    imports: Mapping[str, str]
    document_kind: DocumentKind

    def __init__(
        self,
        url: str,
        text: str,
        imports: Mapping[str, str] | None = None,
        document_kind: DocumentKind | None = None,
    ) -> None:
        validate_url(url)
        if not isinstance(text, str):
            raise TypeError("Model source text must be a string")
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "text", text)
        object.__setattr__(
            self, "imports", freeze_imports({} if imports is None else imports)
        )
        object.__setattr__(
            self, "document_kind", resolve_document_kind(url, document_kind)
        )


def resolve_source(
    source: str | Path | ModelSource, *, url: str | None, root: Path
) -> tuple[str, str, Mapping[str, str] | None]:
    if isinstance(source, Path):
        return source.resolve().as_uri(), read_text(source), None
    if isinstance(source, ModelSource):
        return source.url, source.text, source.imports
    if isinstance(source, str):
        return url or (root / DEFAULT_SOURCE_FILENAME).as_uri(), source, None
    raise TypeError("source must be Malloy text, a Path, or ModelSource")


def read_text(path: Path) -> str:
    """Read authored UTF-8 without changing line endings or string literal contents."""
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()
