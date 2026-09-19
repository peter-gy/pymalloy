from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import urlsplit

from pymalloy._model import DEFAULT_CONNECTION
from pymalloy._model.source import ModelSource
from pymalloy._protocol.givens import encode_givens, given_values
from pymalloy._protocol.snapshot import freeze


@dataclass(frozen=True)
class QueryCell:
    name: str
    sql: str
    kind: Literal["select", "copy"]

    def __post_init__(self) -> None:
        if self.kind not in {"select", "copy"}:
            raise ValueError("QueryCell kind must be 'select' or 'copy'")


@dataclass(frozen=True)
class Markdown:
    text: str


class Profile(StrEnum):
    PRECOMPILED = "precompiled"
    HEADLESS = "headless"
    WIDGET = "widget"


def remote_urls(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, str) or any(
        not isinstance(url, str)
        or urlsplit(url).scheme not in {"http", "https"}
        or not urlsplit(url).netloc
        for url in values
    ):
        raise ValueError("remote_files must contain absolute HTTP(S) URLs")
    return tuple(values)


def native_extensions(
    values: Sequence[str], profile: Profile, remote_files: Collection[str]
) -> tuple[str, ...]:
    if isinstance(values, str) or any(
        not isinstance(name, str) or not name for name in values
    ):
        raise ValueError("extensions must contain nonempty extension names")
    if profile == Profile.WIDGET and values:
        raise ValueError(
            "Native extensions apply only to precompiled or headless notebooks"
        )
    required = ("httpfs",) if remote_files and profile != Profile.WIDGET else ()
    return tuple(dict.fromkeys((*values, *required)))


@dataclass(frozen=True)
class Document:
    title: str
    cells: tuple[QueryCell | Markdown, ...]
    data_root: Path
    database: Path | None = None
    source: ModelSource | None = None
    givens: Mapping[str, Any] = field(default_factory=dict)
    profile: Profile = Profile.PRECOMPILED
    files: Mapping[str, Path] = field(default_factory=dict)
    connection_name: str = DEFAULT_CONNECTION
    remote_files: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.connection_name, str) or not self.connection_name:
            raise ValueError("connection_name must be a nonempty string")
        object.__setattr__(self, "profile", Profile(self.profile))
        object.__setattr__(self, "remote_files", remote_urls(self.remote_files))
        object.__setattr__(
            self,
            "extensions",
            native_extensions(self.extensions, self.profile, self.remote_files),
        )
        object.__setattr__(
            self, "givens", freeze(given_values(encode_givens(self.givens)))
        )
        object.__setattr__(self, "files", MappingProxyType(dict(self.files)))
        if self.profile != Profile.WIDGET and any(
            location.resolve() != (self.data_root / alias).resolve()
            for alias, location in self.files.items()
        ):
            raise ValueError(
                "Native notebook files must resolve relative to data_root; "
                "use absolute source paths for other files"
            )
        if (self.profile == Profile.PRECOMPILED) != (self.source is None):
            raise ValueError(
                "Headless and widget documents require captured model source"
            )

    @property
    def queries(self) -> tuple[QueryCell, ...]:
        return tuple(cell for cell in self.cells if isinstance(cell, QueryCell))
