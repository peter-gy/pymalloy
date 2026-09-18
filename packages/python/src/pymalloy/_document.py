from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import urlsplit

from pymalloy._connection import DEFAULT_CONNECTION
from pymalloy._givens import encode_givens, given_values
from pymalloy._snapshot import freeze
from pymalloy._source import ModelSource


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
    SERVER = "server"
    WIDGET = "widget"


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
        if isinstance(self.remote_files, str) or any(
            not isinstance(url, str)
            or urlsplit(url).scheme not in {"http", "https"}
            or not urlsplit(url).netloc
            for url in self.remote_files
        ):
            raise ValueError("remote_files must contain absolute HTTP(S) URLs")
        object.__setattr__(self, "remote_files", tuple(self.remote_files))
        if isinstance(self.extensions, str) or any(
            not isinstance(name, str) or not name for name in self.extensions
        ):
            raise ValueError("extensions must contain nonempty extension names")
        object.__setattr__(
            self,
            "extensions",
            tuple(
                dict.fromkeys(
                    (
                        *self.extensions,
                        *(
                            ("httpfs",)
                            if self.remote_files and self.profile != Profile.WIDGET
                            else ()
                        ),
                    )
                )
            ),
        )
        object.__setattr__(self, "profile", Profile(self.profile))
        if self.profile == Profile.WIDGET and self.extensions:
            raise ValueError(
                "Native extensions apply only to precompiled or server notebooks"
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
                "Server and widget documents require captured model source"
            )

    @property
    def queries(self) -> tuple[QueryCell, ...]:
        return tuple(cell for cell in self.cells if isinstance(cell, QueryCell))
