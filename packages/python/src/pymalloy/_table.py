"""Native table references with optional Python-owned input data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pymalloy._identifiers import identifier
from pymalloy._inputs import DataInput


def table_path(path: str | Path) -> str:
    return (
        "'" + path.as_posix().replace("'", "''") + "'"
        if isinstance(path, Path)
        else path
    )


@dataclass(frozen=True, eq=False)
class TableReference:
    connection: str
    path: str
    source: str | None = None
    data: DataInput | None = None

    def render(self, *, materialize: bool = False) -> str:
        if self.data is not None and materialize:
            path = table_path(self.data.materialize().path)
        elif self.source is not None:
            return self.source
        else:
            path = self.path
        connection = identifier(self.connection)
        return f"{connection}.table({json.dumps(path, ensure_ascii=False)})"

    @property
    def text(self) -> str:
        return self.render()
