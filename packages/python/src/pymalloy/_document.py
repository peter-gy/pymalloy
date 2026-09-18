from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

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


@dataclass(frozen=True)
class Document:
    title: str
    cells: tuple[Query | Markdown, ...]
    data_root: Path
    database: Path | None = None
    source: ModelSource | None = None
    _givens_json: str = field(default="{}", repr=False)
    profile: Literal["precompiled", "native", "widget"] = "precompiled"
    _widget_files: tuple[tuple[str, str], ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        if self.profile not in {"precompiled", "native", "widget"}:
            raise ValueError("profile must be 'precompiled', 'native', or 'widget'")
        if (self.profile == "precompiled") != (self.source is None):
            raise ValueError(
                "Native and widget documents require captured model source"
            )

    @property
    def givens(self) -> dict:
        """A detached snapshot of the values supplied to the hydrated model."""
        return json.loads(self._givens_json)

    @property
    def queries(self) -> tuple[Query, ...]:
        return tuple(cell for cell in self.cells if isinstance(cell, Query))
