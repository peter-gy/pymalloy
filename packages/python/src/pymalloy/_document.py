from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from pymalloy._givens import encode_givens, given_values
from pymalloy._source import ModelSource


@dataclass(frozen=True)
class Query:
    name: str
    sql: str
    kind: Literal["select", "copy"]

    def __post_init__(self) -> None:
        if self.kind not in {"select", "copy"}:
            raise ValueError("Query kind must be 'select' or 'copy'")


@dataclass(frozen=True)
class Markdown:
    text: str


class Profile(StrEnum):
    PRECOMPILED = "precompiled"
    SERVER = "server"
    WIDGET = "widget"


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class Document:
    title: str
    cells: tuple[Query | Markdown, ...]
    data_root: Path
    database: Path | None = None
    source: ModelSource | None = None
    givens: Mapping[str, Any] = field(default_factory=dict)
    profile: Profile = Profile.PRECOMPILED
    files: Mapping[str, Path] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile", Profile(self.profile))
        object.__setattr__(
            self, "givens", _freeze(given_values(encode_givens(self.givens)))
        )
        object.__setattr__(self, "files", MappingProxyType(dict(self.files)))
        if (self.profile == Profile.PRECOMPILED) != (self.source is None):
            raise ValueError(
                "Server and widget documents require captured model source"
            )

    @property
    def queries(self) -> tuple[Query, ...]:
        return tuple(cell for cell in self.cells if isinstance(cell, Query))
