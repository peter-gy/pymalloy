"""Compiler diagnostics, documentation lint, and executable model assertions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import unquote, urlsplit

from msgspec import structs

from pymalloy._model import DEFAULT_CONNECTION
from pymalloy._model.source import ModelSource, read_text
from pymalloy._protocol.givens import given_values
from pymalloy._protocol.records import NativeMetadata
from pymalloy.analysis import CheckReport, Diagnostic
from pymalloy.execution import ExecutionContext
from pymalloy.result import Result

if TYPE_CHECKING:
    from pymalloy._authoring.draft import Draft


@dataclass(frozen=True)
class DocumentationPolicy:
    """Choose which model objects require nonempty native descriptions.

    Parameters
    ----------
    routes : tuple of str, default ('"',)
        Accepted annotation routes. Any nonempty annotation on one route satisfies
        the presence check. Use an application route to check project-specific notes.
    kinds : tuple of str, default ("source", "measure", "view")
        Object kinds to inspect in Malloy metadata.
    severity : {"warning", "error"}, default "warning"
        Severity of missing-description findings. Warnings alone do not fail
        Validation.ok, but require_valid(warnings_as_errors=True) rejects them.

    Examples
    --------
    >>> import pymalloy as pm
    >>> from pymalloy.validation import DocumentationPolicy
    >>> policy = DocumentationPolicy(kinds=("measure",), severity="error")
    >>> candidate = pm.draft().define(values=pm.sql("SELECT 1 AS n").extend(
    ...     pm.measure(total=pm.col("n").sum().doc("Total observed n."))))
    >>> candidate.check(documentation=policy).ok
    True
    """

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


def _documentation(
    metadata: NativeMetadata,
    policy: DocumentationPolicy | None = None,
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
    report: CheckReport, policy: DocumentationPolicy | None = None
) -> CheckReport:
    notes = _documentation(report.model, policy) if report.ok else ()
    return structs.replace(
        report,
        ok=report.ok and not any(note.severity == "error" for note in notes),
        diagnostics=tuple(report.diagnostics) + notes,
    )


@dataclass(frozen=True)
class DataCheck:
    """Outcome of one named counterexample query.

    Attributes
    ----------
    name : str
        Assertion key supplied to Draft.validate.
    status : {"passed", "failed", "error", "skipped"}
        Zero counterexamples, an observed counterexample, query failure, or an
        assertion not run because an earlier required stage failed.
    result : Result or None
        Materialized check output, bounded to one counterexample on failure.
    error : str or None
        Failure description when available.
    diagnostics : tuple of Diagnostic
        Authored compiler findings associated with this check.
    execution : ExecutionContext or None
        Detached context for a data-engine failure.
    """

    name: str
    status: Literal["passed", "failed", "error", "skipped"]
    result: Result | None = None
    error: str | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    execution: ExecutionContext | None = None


@dataclass(frozen=True)
class Validation:
    """Evidence for a draft revision and its data at validation time.

    Returned by Draft.validate. Inspect checks and diagnostics before saving or
    bundling. A successful report proves only the supplied assertions on the
    observed data, not the model's business meaning or future data quality.

    Attributes
    ----------
    draft : Draft
        Captured revision, imported source and managed data inputs.
    diagnostics : tuple of Diagnostic
        Compiler and optional documentation findings.
    checks : tuple of DataCheck
        Named assertion outcomes in submission order.
    error : str or None
        Model-level authored failure, if any.
    queries : tuple of str
        Available query names from the validated model.
    connection_name : str
        Connection identifier retained for bundle replay.
    givens : dict
        Detached bound values used during validation.
    ok : bool
        Whether compilation and every supplied check succeeded, with no errors.

    Examples
    --------
    >>> import pymalloy as pm
    >>> accepted = pm.draft().define(values=pm.sql("SELECT 42 AS n")).validate()
    >>> accepted.ok
    True
    >>> accepted.checks
    ()
    """

    draft: Draft
    diagnostics: tuple[Diagnostic, ...]
    checks: tuple[DataCheck, ...]
    error: str | None = None
    _givens_json: str = field(default="{}", repr=False)
    queries: tuple[str, ...] = ()
    connection_name: str = DEFAULT_CONNECTION

    @property
    def givens(self) -> dict[str, Any]:
        """Return a detached dictionary of the exact validated parameter bindings."""
        return given_values(json.loads(self._givens_json))

    @property
    def ok(self) -> bool:
        """Return True when compilation and all supplied checks pass, ignoring warnings."""
        return (
            self.error is None
            and not any(d.severity == "error" for d in self.diagnostics)
            and all(c.status == "passed" for c in self.checks)
        )

    def require_valid(self, *, warnings_as_errors: bool = False) -> Validation:
        """Require successful evidence before continuing an authoring workflow.

        Parameters
        ----------
        warnings_as_errors : bool, default False
            Reject warning diagnostics as well as errors and non-passing checks.

        Returns
        -------
        Validation
            This report, allowing ``draft.validate(...).require_valid()``.

        Raises
        ------
        ValueError
            Validation failed, a check was skipped/errored, or strict warnings exist.

        Examples
        --------
        >>> import pymalloy as pm
        >>> accepted = pm.draft().define(values=pm.sql("SELECT 42 AS n")).validate()
        >>> accepted.require_valid() is accepted
        True
        """
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
        """Return the accepted closed source snapshot for export.

        Raises ValueError for failed validation or missing captured imports. Source
        contains code, not table data. Use export.bundle to publish managed inputs too.
        """
        self.require_valid()
        if self.draft.imports is None:
            raise ValueError("Validation has no captured source graph")
        return ModelSource(
            self.draft.url,
            self.draft.syntax.render(materialize=True),
            self.draft.imports,
            self.draft.document_kind,
        )

    def save(
        self,
        path: str | Path | None = None,
        *,
        overwrite: bool = False,
        warnings_as_errors: bool = False,
    ) -> Path:
        """Save an accepted root revision with import-change checks.

        Parameters
        ----------
        path : str or pathlib.Path, optional
            Destination, defaulting to the loaded source path. Validated imports must
            be saved beside their original root so relative resolution is preserved.
        overwrite : bool, default False
            Permit replacing an unrelated destination. Existing loaded files retain
            the observed-revision checks of Draft.save.
        warnings_as_errors : bool, default False
            Reject warnings before writing, in addition to failed validation.

        Returns
        -------
        pathlib.Path
            Absolute saved path. Changed imported source is rejected. Captured data
            requires export.bundle rather than a source-only save.

        Examples
        --------
        >>> import pymalloy as pm
        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>> accepted = pm.draft().define(values=pm.sql("SELECT 42 AS n")).validate()
        >>> with TemporaryDirectory() as directory:
        ...     saved = accepted.save(Path(directory) / "model.malloy")
        ...     print(saved.is_file())
        True
        """
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
