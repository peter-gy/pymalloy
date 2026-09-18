"""Compiler diagnostics, documentation lint, and executable model assertions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import unquote, urlsplit

from msgspec import UNSET, structs

from pymalloy._records import FieldInfoWithMeasure, FieldInfoWithView, NativeMetadata
from pymalloy._source import read_text
from pymalloy.analysis import CheckReport, Diagnostic
from pymalloy.result import Result

if TYPE_CHECKING:
    from pymalloy._draft import Draft


def _documentation(metadata: NativeMetadata) -> tuple[Diagnostic, ...]:
    issues = []
    for source in metadata.sources:
        items = [(source.name, "source", source.annotations)]
        for field in source.schema.fields:
            if isinstance(field, (FieldInfoWithMeasure, FieldInfoWithView)):
                kind = "measure" if isinstance(field, FieldInfoWithMeasure) else "view"
                items.append((f"{source.name}.{field.name}", kind, field.annotations))
        for name, kind, notes in items:
            if notes is not UNSET and any(
                a.value.strip().startswith("#(doc)") and a.value.strip()[6:].strip()
                for a in notes
            ):
                continue
            issues.append(
                Diagnostic(
                    code=f"missing-{kind}-doc",
                    severity="warning",
                    message=f"Document {kind} '{name}' with #(doc), including its meaning and grain or units.",
                    location=None,
                    replacement=None,
                    error_tag=None,
                    data={"name": name},
                )
            )
    return tuple(issues)


def _checked(report: CheckReport) -> CheckReport:
    return structs.replace(
        report,
        diagnostics=tuple(report.diagnostics)
        + (_documentation(report.model) if report.ok else ()),
    )


@dataclass(frozen=True)
class DataCheck:
    name: str
    status: Literal["passed", "failed", "error", "skipped"]
    result: Result | None = None
    error: str | None = None
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class Validation:
    """Evidence for one immutable draft and the supplied data at validation time."""

    draft: Draft
    diagnostics: tuple[Diagnostic, ...]
    checks: tuple[DataCheck, ...]
    error: str | None = None

    @property
    def ok(self) -> bool:
        return (
            self.error is None
            and not any(d.severity == "error" for d in self.diagnostics)
            and all(c.status == "passed" for c in self.checks)
        )

    def require_valid(self, *, warnings_as_errors: bool = False) -> Validation:
        if not self.ok or (
            warnings_as_errors
            and any(d.severity == "warning" for d in self.diagnostics)
        ):
            failures = [d.message for d in self.diagnostics if d.severity != "debug"]
            failures.extend(
                f"{c.name}: {c.error or c.status}"
                for c in self.checks
                if c.status != "passed"
            )
            if self.error:
                failures.append(self.error)
            raise ValueError("Model validation failed: " + "; ".join(failures))
        return self

    def save(
        self,
        path: str | Path | None = None,
        *,
        overwrite: bool = False,
        warnings_as_errors: bool = False,
    ) -> Path:
        """Save the validated root revision, rejecting failed or incomplete checks."""
        self.require_valid(warnings_as_errors=warnings_as_errors)
        if self.draft.imports:
            root = urlsplit(self.draft.url)
            target = Path(path).resolve() if path is not None else self.draft.path
            if (
                root.scheme != "file"
                or target is None
                or target.parent != Path(unquote(root.path)).parent
            ):
                raise ValueError(
                    "Save validated imports beside the original model, or save the draft and revalidate at its destination"
                )
            for url, text in self.draft.imports.items():
                imported = urlsplit(url)
                if (
                    imported.scheme != "file"
                    or read_text(Path(unquote(imported.path))) != text
                ):
                    raise ValueError(f"Imported model changed since validation: {url}")
        return self.draft.save(path, overwrite=overwrite)
