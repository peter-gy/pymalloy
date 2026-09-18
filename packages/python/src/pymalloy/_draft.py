from __future__ import annotations

import json
import keyword
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from difflib import unified_diff
from pathlib import Path
from typing import TYPE_CHECKING, Any, Unpack

from pymalloy._persistence import write_text
from pymalloy._source import ModelSource, freeze_imports, resolve_source, validate_url
from pymalloy._syntax import Fragment, Kind, expression, from_wire, named_clause, syntax

if TYPE_CHECKING:
    from pymalloy._server.api import _RuntimeOptions
    from pymalloy._server.runtime import Model
    from pymalloy.analysis import CheckReport
    from pymalloy.validation import Validation


@dataclass(frozen=True, eq=False)
class Draft:
    """An immutable model syntax tree, independent of compiler and engine lifetime."""

    syntax: Fragment = field(default_factory=lambda: syntax(kind="document"))
    url: str = field(default_factory=lambda: (Path.cwd() / "model.malloy").as_uri())
    imports: Mapping[str, str] | None = None
    path: Path | None = field(default=None, repr=False, compare=False)
    _original: str | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.syntax.kind != "document":
            raise ValueError("A draft requires document syntax")
        validate_url(self.url)
        if self.imports is not None:
            object.__setattr__(self, "imports", freeze_imports(self.imports))

    @property
    def text(self) -> str:
        return self.syntax.text

    @property
    def names(self) -> tuple[str, ...]:
        return self.syntax.names

    def __getitem__(self, name: str) -> Fragment:
        return expression(self.syntax[name])

    def append(self, *parts: str | Fragment) -> Draft:
        """Append syntax verbatim. Use declarations to introduce named editing slots."""
        return replace(self, syntax=syntax(*self.syntax.parts, *parts, kind="document"))

    def _define(self, kind: Kind, values: Mapping[str, Fragment]) -> Draft:
        existing = self.syntax._scope
        updates = {name: value for name, value in values.items() if name in existing}
        for name, target in self.syntax._select(updates).items():
            if target.kind != kind:
                raise ValueError(f"{name!r} is not a {kind} declaration")
        result = self.syntax.replace(**updates) if updates else self.syntax
        additions = [
            named_clause(kind, {name: value}, kind=kind)
            for name, value in values.items()
            if name not in existing
        ]
        if additions:
            parts: list[str | Fragment] = [result._line_break]
            for addition in additions:
                parts.extend((addition, "\n"))
            result = syntax(*result.parts, *parts, kind="document")
        return replace(self, syntax=result)

    def define(self, **sources: Fragment) -> Draft:
        """Bind or replace named source expressions, preserving existing declaration trivia."""
        return self._define("source", sources)

    def queries(self, **queries: Fragment) -> Draft:
        """Bind or replace named query expressions."""
        return self._define("query", queries)

    def include(self, url: str | Path) -> Draft:
        """Append a live import. Closed snapshots keep their captured import set."""
        if self.imports is not None:
            raise ValueError(
                "Closed snapshots require imported text in their imports mapping"
            )
        value = url.resolve().as_uri() if isinstance(url, Path) else url
        return self.append(
            self.syntax._line_break, f"import {json.dumps(value, ensure_ascii=False)}\n"
        )

    def diff(self, previous: Draft | None = None) -> str:
        before = previous.text if previous is not None else (self._original or "")
        return "".join(
            unified_diff(
                before.splitlines(True),
                self.text.splitlines(True),
                fromfile="before.malloy",
                tofile="after.malloy",
            )
        )

    def format(self) -> Draft:
        from pymalloy._server.tooling import format as format_source

        formatted = read_model(format_source(self.text), url=self.url)
        return replace(self, syntax=formatted.syntax)

    def _input(self) -> str | ModelSource:
        return (
            self.text
            if self.imports is None
            else ModelSource(self.url, self.text, self.imports)
        )

    def check(self, **options: Unpack[_RuntimeOptions]) -> CheckReport:
        """Compile and return language diagnostics plus documentation warnings."""
        from pymalloy._server import load_api
        from pymalloy.validation import _checked

        return _checked(load_api().check(self._input(), url=self.url, **options))

    def compile(self, **options: Unpack[_RuntimeOptions]) -> Model:
        from pymalloy._server import load_api

        return load_api().model(self._input(), url=self.url, **options)

    def validate(
        self,
        checks: Mapping[str, Fragment] | None = None,
        *,
        givens: Mapping[str, Any] | None = None,
        **options: Unpack[_RuntimeOptions],
    ) -> Validation:
        """Compile once and execute named queries that must return no counterexamples."""
        from pymalloy._server import load_api

        return load_api().validate(self, checks or {}, givens=givens, **options)

    def save(self, path: str | Path | None = None, *, overwrite: bool = False) -> Path:
        target = Path(path).resolve() if path is not None else self.path
        if target is None:
            raise ValueError("Choose a destination for this draft")
        return write_text(
            target,
            self.text,
            expected=self._original if target == self.path else None,
            overwrite=overwrite,
        )

    def to_python(self, *, name: str = "model") -> str:
        """Emit symbolic Python for equivalent Malloy, normalizing supported scalar spelling."""
        if not name.isidentifier() or keyword.iskeyword(name):
            raise ValueError("Choose a Python variable name")
        from pymalloy._python import python_source

        return python_source(self, name)


def draft(
    *parts: str | Fragment,
    url: str | None = None,
    imports: Mapping[str, str] | None = None,
) -> Draft:
    """Compose a model without parsing or I/O. Use read_model to import existing Malloy."""
    node = syntax(*parts, kind="document")
    return Draft(node, imports=imports) if url is None else Draft(node, url, imports)


def read_model(source: str | Path | ModelSource, *, url: str | None = None) -> Draft:
    """Parse a plain Malloy model into lossless editable syntax using the installed compiler."""
    from pymalloy._server.tooling import parse_syntax

    identity, text, imports = resolve_source(
        source, url=url or (Path.cwd() / "model.malloy").as_uri(), root=Path.cwd()
    )
    path = source.resolve() if isinstance(source, Path) else None
    parsed = from_wire(parse_syntax(text, url=identity))
    if not isinstance(parsed, Fragment):
        raise TypeError("Compiler returned a scalar for a model document")
    return Draft(parsed, identity, imports, path, text if path is not None else None)
