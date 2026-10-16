from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, get_args
from urllib.parse import urlsplit

from pymalloy._model.inputs import Input
from pymalloy._notebook import NotebookDisplay
from pymalloy._protocol.records import DocumentKind, ParseReport

DEFAULT_SOURCE_FILENAME = "model.malloy"
_DOCUMENT_KINDS = get_args(DocumentKind.__value__)


def resolve_document_kind(url: str, kind: DocumentKind | None = None) -> DocumentKind:
    if kind is not None:
        if kind not in _DOCUMENT_KINDS:
            raise ValueError(
                "document_kind must be " + " or ".join(map(repr, _DOCUMENT_KINDS))
            )
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
class ModelSource(NotebookDisplay):
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
    inputs : tuple of Input, default ()
        Captured data owners referenced by logical paths in the source graph.

    Notes
    -----
    Constructing the snapshot validates its shape, not the model or import closure.
    Captured inputs retain their values independently of the producer and runtime.
    Use Model.source to capture resolved imports and export.bundle to copy inputs.

    Examples
    --------
    >>> import pymalloy as pm
    >>> source = pm.ModelSource(
    ...     "memory://tour/report.malloy",
    ...     "import 'base.malloy'\nrun: values -> {select: n}",
    ...     {"memory://tour/base.malloy": "source: values is duckdb.sql('SELECT 42 AS n')"},
    ... )
    >>> pm.connect().model(source).query().run().to_pylist()
    [{'n': 42}]
    """

    url: str
    text: str
    imports: Mapping[str, str]
    document_kind: DocumentKind
    inputs: tuple[Input, ...]

    def __init__(
        self,
        url: str,
        text: str,
        imports: Mapping[str, str] | None = None,
        document_kind: DocumentKind | None = None,
        *,
        inputs: tuple[Input, ...] = (),
    ) -> None:
        validate_url(url)
        if not isinstance(text, str):
            raise TypeError("Model source text must be a string")
        if not isinstance(inputs, tuple) or not all(
            isinstance(value, Input) for value in inputs
        ):
            raise TypeError("Model source inputs must be a tuple of Input owners")
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "text", text)
        object.__setattr__(
            self, "imports", freeze_imports({} if imports is None else imports)
        )
        object.__setattr__(
            self, "document_kind", resolve_document_kind(url, document_kind)
        )
        object.__setattr__(self, "inputs", inputs)


def resolve_source(
    source: str | Path | ModelSource, *, url: str | None, root: Path
) -> tuple[str, str, Mapping[str, str] | None]:
    if isinstance(source, Path):
        return source.resolve().as_uri(), read_text(source), None
    if isinstance(source, ModelSource):
        return source.url, source.text, source.imports
    if isinstance(source, str):
        name = source.strip()
        if name.endswith((".malloy", ".malloynb", ".malloysql")) and not any(
            character.isspace() for character in name
        ):
            raise TypeError(
                f"A string is Malloy source text. Pass Path({name!r}) to read a file."
            )
        return url or (root / DEFAULT_SOURCE_FILENAME).as_uri(), source, None
    raise TypeError("source must be Malloy text, a Path, or ModelSource")


def read_text(path: Path) -> str:
    """Read authored UTF-8 without changing line endings or string literal contents."""
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def local_path(url: str) -> Path:
    from urllib import request

    # Pyrefly's Windows stub inherits nturl2path's deprecation through this public re-export.
    url2pathname: Callable[[str], str] = request.url2pathname  # pyrefly: ignore [deprecated]

    parsed = urlsplit(url)
    if parsed.scheme == "file" and parsed.netloc in {"", "localhost"}:
        return Path(url2pathname(parsed.path))
    path = Path(url)
    if len(parsed.scheme) == 1 and path.is_absolute() and path.drive.endswith(":"):
        return Path(url2pathname(url))
    raise ValueError(f"Import '{url}' must be a local file")


if TYPE_CHECKING:
    from pymalloy._authoring.draft import Draft


def open_source(
    source: str | Path | ModelSource | Draft,
    *,
    url: str | None,
    document_kind: DocumentKind | None,
    root: Path,
    materialize: bool = False,
    parse: Callable[[str, str, DocumentKind], ParseReport] | None = None,
):
    from pymalloy._authoring.draft import Draft

    if isinstance(source, (Path, ModelSource, Draft)):
        identity = source.resolve().as_uri() if isinstance(source, Path) else source.url
        if url is not None and url != identity:
            raise ValueError("url conflicts with source identity")
    if isinstance(source, (Draft, ModelSource)) and document_kind is None:
        document_kind = source.document_kind
    if isinstance(source, Draft):
        url = source.url
        source = (
            source._input()
            if materialize
            else (
                source.text
                if source.imports is None
                else ModelSource(
                    source.url, source.text, source.imports, source.document_kind
                )
            )
        )
    identity, text, imports = resolve_source(source, url=url, root=root)
    kind = resolve_document_kind(identity, document_kind)
    if materialize and isinstance(source, ModelSource) and source.inputs:
        assert parse is not None
        from itertools import accumulate

        from pymalloy.authoring import table

        captures = {value.reference: value for value in source.inputs}

        def render(text: str, identity: str, kind: DocumentKind) -> str:
            assert parse is not None
            parsed = parse(text, identity, kind)
            offsets = list(
                accumulate((len(line) + 1 for line in text.split("\n")), initial=0)
            )
            edits = []
            for reference in parsed.tables:
                if reference.path in captures:
                    span = reference.range
                    edits.append(
                        (
                            offsets[span.start.line] + span.start.character,
                            offsets[span.end.line] + span.end.character,
                            table(
                                captures[reference.path]._materialize().path,
                                connection=reference.connection,
                            ).text,
                        )
                    )
            for start, end, replacement in sorted(edits, reverse=True):
                text = text[:start] + replacement + text[end:]
            return text

        text = render(text, identity, kind)
        imports = {
            identity: render(text, identity, "model")
            for identity, text in source.imports.items()
        }
    return identity, text, imports, kind
