from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit


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


@dataclass(frozen=True)
class ModelSource:
    """Original model text and captured imports, indexed by absolute URL."""

    url: str
    text: str
    imports: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_url(self.url)
        if not isinstance(self.text, str):
            raise TypeError("Model source text must be a string")
        object.__setattr__(self, "imports", freeze_imports(self.imports))


def resolve_source(
    source: str | Path | ModelSource, *, url: str | None, root: Path
) -> tuple[str, str, Mapping[str, str] | None]:
    if isinstance(source, Path):
        return source.resolve().as_uri(), read_text(source), None
    if isinstance(source, ModelSource):
        return source.url, source.text, source.imports
    if isinstance(source, str):
        return url or (root / "inline.malloy").as_uri(), source, None
    raise TypeError("source must be Malloy text, a Path, or ModelSource")


def read_text(path: Path) -> str:
    """Read authored UTF-8 without changing line endings or string literal contents."""
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()
