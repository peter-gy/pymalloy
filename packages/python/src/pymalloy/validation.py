"""Compiler diagnostics, documentation lint, and executable model assertions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import unquote, urlsplit

from msgspec import structs

from pymalloy._records import NativeMetadata
from pymalloy._source import ModelSource, read_text
from pymalloy.analysis import CheckReport, Diagnostic
from pymalloy.execution import ExecutionContext
from pymalloy.result import Result

if TYPE_CHECKING:
    from pymalloy._draft import Draft


@dataclass(frozen=True)
class DocumentationPolicy:
    """Routes and object kinds required by authoring checks. Malloy owns route parsing."""

    routes: tuple[str, ...] = ('"',)
    kinds: tuple[str, ...] = ("source", "measure", "view")
    severity: Literal["warning", "error"] = "warning"

    def __post_init__(self) -> None:
        for values in (self.routes, self.kinds):
            if not isinstance(values, tuple) or not all(
                isinstance(v, str) for v in values
            ):
                raise TypeError(
                    "Documentation routes and kinds must be tuples of strings"
                )
        if self.severity not in {"warning", "error"}:
            raise ValueError("Documentation severity must be warning or error")


_DEFAULT_DOCUMENTATION = DocumentationPolicy()


def _documentation(
    metadata: NativeMetadata,
    policy: DocumentationPolicy | None = _DEFAULT_DOCUMENTATION,
) -> tuple[Diagnostic, ...]:
    if policy is None:
        return ()
    issues = []
    for item in metadata.annotations:
        if item.kind not in policy.kinds or any(
            note.route in policy.routes and note.content.strip()
            for note in item.annotations
        ):
            continue
        name = ".".join(item.path)
        issues.append(
            Diagnostic(
                code=f"missing-{item.kind}-doc",
                severity=policy.severity,
                message=f"Document {item.kind} '{name}' using one of the annotation routes {policy.routes!r}, including its meaning and grain or units.",
                location=None,
                replacement=None,
                error_tag=None,
                data={"path": list(item.path), "routes": list(policy.routes)},
            )
        )
    return tuple(issues)


def _checked(
    report: CheckReport, policy: DocumentationPolicy | None = _DEFAULT_DOCUMENTATION
) -> CheckReport:
    notes = _documentation(report.model, policy) if report.ok else ()
    return structs.replace(
        report,
        ok=report.ok and not any(note.severity == "error" for note in notes),
        diagnostics=tuple(report.diagnostics) + notes,
    )


@dataclass(frozen=True)
class DataCheck:
    name: str
    status: Literal["passed", "failed", "error", "skipped"]
    result: Result | None = None
    error: str | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    execution: ExecutionContext | None = None


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

    @property
    def source(self) -> ModelSource:
        """The closed source graph accepted by validation, ready for export."""
        self.require_valid()
        if self.draft.imports is None:
            raise ValueError("Validation has no captured source graph")
        return ModelSource(self.draft.url, self.draft.text, self.draft.imports)

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
