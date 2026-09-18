"""Serializable results from Malloy's language tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

__all__ = [
    "CheckResult",
    "Diagnostic",
    "Location",
    "NativeMetadata",
    "Position",
    "Range",
]


@dataclass(frozen=True)
class Position:
    line: int
    character: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0 for value in (self.line, self.character)
        ):
            raise ValueError(
                "Source positions require nonnegative integer line and character"
            )


@dataclass(frozen=True)
class Range:
    start: Position
    end: Position


@dataclass(frozen=True)
class Location:
    url: str
    range: Range


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: Literal["error", "warning", "debug"]
    message: str
    location: Location | None = None
    replacement: str | None = None
    data: Any = None
    error_tag: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def _from_wire(cls, value: dict[str, Any]) -> Diagnostic:
        at = value.get("location")
        return cls(
            code=value["code"],
            severity=value["severity"],
            message=value["message"],
            location=Location(
                at["url"],
                Range(Position(**at["range"]["start"]), Position(**at["range"]["end"])),
            )
            if at
            else None,
            replacement=value.get("replacement"),
            data=value.get("data"),
            error_tag=value.get("error_tag"),
        )


@dataclass(frozen=True)
class NativeMetadata:
    """Schemas in the bundled Malloy compiler's native metadata format."""

    model: dict[str, Any] | None = None
    sources: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class CheckResult:
    url: str
    compiler_version: str
    diagnostics: tuple[Diagnostic, ...] = ()
    native: NativeMetadata = field(default_factory=NativeMetadata)
    queries: tuple[str, ...] = ()
    symbols: tuple[dict[str, Any], ...] = ()
    tables: tuple[dict[str, Any], ...] = ()
    imports: tuple[dict[str, Any], ...] = ()
    completions: tuple[dict[str, Any], ...] = ()
    help: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        """Return a detached report suitable for `json.dumps`."""
        return {"ok": self.ok, **asdict(self)}

    @classmethod
    def _from_wire(cls, value: dict[str, Any]) -> CheckResult:
        return cls(
            url=value["url"],
            compiler_version=value["compiler_version"],
            diagnostics=tuple(
                Diagnostic._from_wire(item) for item in value["diagnostics"]
            ),
            native=NativeMetadata(
                model=value["native"]["model"],
                sources=tuple(value["native"]["sources"]),
            ),
            queries=tuple(value.get("queries", [])),
            symbols=tuple(value.get("symbols", [])),
            tables=tuple(value.get("tables", [])),
            imports=tuple(value.get("imports", [])),
            completions=tuple(value.get("completions", [])),
            help=value.get("help"),
        )
