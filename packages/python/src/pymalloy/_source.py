from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ModelSource:
    """Original model text and captured imports, indexed by absolute URL."""

    url: str
    text: str
    imports: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.url, str) or not urlsplit(self.url).scheme:
            raise ValueError("Model source requires an absolute root URL")
        if not isinstance(self.text, str):
            raise TypeError("Model source text must be a string")
        if not all(
            isinstance(url, str) and urlsplit(url).scheme and isinstance(source, str)
            for url, source in self.imports.items()
        ):
            raise ValueError("Model imports must map absolute URLs to source text")
        object.__setattr__(self, "imports", MappingProxyType(dict(self.imports)))
