from __future__ import annotations

import json
import keyword
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from difflib import unified_diff
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal

from pymalloy._authoring.syntax import (
    Syntax,
    from_wire,
    named_clause,
    syntax,
)
from pymalloy._model.inputs import Input
from pymalloy._model.persistence import write_text
from pymalloy._model.source import (
    DEFAULT_SOURCE_FILENAME,
    DocumentKind,
    ModelSource,
    freeze_imports,
    resolve_document_kind,
    resolve_source,
    validate_url,
)
from pymalloy._notebook import NotebookDisplay

if TYPE_CHECKING:
    from pymalloy.authoring import Source, View
    from pymalloy.expressions import Expr


@dataclass(frozen=True, eq=False)
class Draft(NotebookDisplay):
    """An immutable, editable model revision with optional captured inputs.

    Use draft to construct one or read_model to parse existing Malloy. Editing
    methods return new drafts. They do not change the original or run queries.

    Attributes
    ----------
    text : str
        Current Malloy source. Captured inputs use logical Parquet references.
    names : tuple of str
        Top-level named declarations in authored order.
    url : str
        Absolute source identity and base for relative imports.
    imports : mapping or None
        Closed imported source text, or None for live resolution at compile time.
    inputs : tuple of Input
        Immutable Python data captures retained by this draft.
    path : pathlib.Path or None
        Original file path when loaded with read_model(Path(...)).

    Examples
    --------
    >>> import pymalloy as pm
    >>> initial = pm.draft().sources(values=pm.sql("SELECT 1 AS n"))
    >>> revised = initial.queries(total=pm.source("values").pipe(
    ...     pm.view().aggregate(n=pm.count())
    ... ))
    >>> initial.names, revised.names
    (('values',), ('values', 'total'))
    """

    document_kind: ClassVar[DocumentKind] = "model"
    syntax: Syntax = field(default_factory=lambda: syntax(kind="document"))
    url: str = field(
        default_factory=lambda: (Path.cwd() / DEFAULT_SOURCE_FILENAME).as_uri()
    )
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
        """Return current Malloy text with logical references for captured inputs."""
        return self.syntax.text

    @property
    def names(self) -> tuple[str, ...]:
        """Return top-level declaration names in authored order."""
        return self.syntax.names

    def __getitem__(self, name: str) -> Source | View | Expr:
        """Select a named declaration's source or query expression.

        Parameters
        ----------
        name : str
            Declaration in this draft's top-level scope.

        Returns
        -------
        Source, View, or Expr
            Editable right-hand side. Missing names raise KeyError and ambiguous
            names raise ValueError. Index again to select a field within a source.

        Examples
        --------
        >>> import pymalloy as pm
        >>> candidate = pm.draft().sources(orders=pm.table("orders.parquet"))
        >>> candidate["orders"].text
        'duckdb.table("orders.parquet")'
        """
        return self.syntax[name]

    def append(self, *parts: str | Source | View) -> Draft:
        r"""Append complete declarations or other syntax verbatim.

        Parameters
        ----------
        *parts : str, Source, or View
            Text/fragments to concatenate. Include needed whitespace or newlines.
            Literal declarations are not parsed into named editing slots.

        Returns
        -------
        Draft
            A new revision retaining the existing source identity and inputs.

        See Also
        --------
        Draft.sources, Draft.queries, read_model

        Examples
        --------
        >>> import pymalloy as pm
        >>> candidate = pm.draft().append("// model notes\n")
        >>> candidate.text
        '// model notes\n'
        """
        return replace(self, syntax=syntax(*self.syntax.parts, *parts, kind="document"))

    def _define(
        self, kind: Literal["source", "query"], values: Mapping[str, Source]
    ) -> Draft:
        from pymalloy.authoring import Source

        if not all(isinstance(value, Source) for value in values.values()):
            raise TypeError("Draft declarations require Source values")
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
            parts: list[str | Syntax] = [result._line_break]
            for addition in additions:
                parts.extend((addition, "\n"))
            result = syntax(*result.parts, *parts, kind="document")
        return replace(self, syntax=result)

    def sources(self, /, **sources: Source) -> Draft:
        """Bind or replace named source expressions.

        Parameters
        ----------
        **sources : Source
            Declaration names mapped to source expressions. Existing declarations
            must have the same kind. Missing names are appended in keyword order.

        Returns
        -------
        Draft
            A new revision preserving existing declaration trivia and other names.

        Examples
        --------
        >>> import pymalloy as pm
        >>> initial = pm.draft().sources(values=pm.sql("SELECT 0 AS n"))
        >>> revised = initial.sources(values=pm.sql("SELECT 1 AS n"))
        >>> revised.names
        ('values',)
        """
        return self._define("source", sources)

    def queries(self, /, **queries: Source) -> Draft:
        """Bind or replace named query expressions.

        Parameters
        ----------
        **queries : Source
            Declaration names mapped to query expressions. Existing declarations
            must have the same kind. Missing names are appended in keyword order.

        Returns
        -------
        Draft
            A new revision preserving existing declaration trivia and other names.

        Examples
        --------
        >>> import pymalloy as pm
        >>> initial = pm.draft().sources(values=pm.sql("SELECT 0 AS n"))
        >>> revised = initial.queries(result=pm.source("values").pipe(pm.view().select(pm.col("n"))))
        >>> revised.names
        ('values', 'result')
        """
        return self._define("query", queries)

    def include(self, url: str | Path) -> Draft:
        r"""Append a live Malloy import at the current end of the draft.

        Parameters
        ----------
        url : str or pathlib.Path
            A string is an import URL resolved relative to the draft identity.
            A Path is resolved to an absolute file URL.

        Returns
        -------
        Draft
            A new draft containing the import. Call include before defining consumers
            of that import. Existing declarations are not reordered. Nothing is loaded
            until compilation.

        Raises
        ------
        ValueError
            The draft already has a closed imports mapping. Construct a new
            ModelSource with the required captured text to extend that snapshot.

        Examples
        --------
        >>> import pymalloy as pm
        >>> candidate = pm.draft(url="file:///project/report.malloy").include("base.malloy")
        >>> candidate.text
        'import "base.malloy"\n'
        """
        if self.imports is not None:
            raise ValueError(
                "Closed snapshots require imported text in their imports mapping"
            )
        value = url.resolve().as_uri() if isinstance(url, Path) else url
        return self.append(
            self.syntax._line_break, f"import {json.dumps(value, ensure_ascii=False)}\n"
        )

    def diff(self, previous: Draft | None = None) -> str:
        """Show a unified source diff for review.

        Parameters
        ----------
        previous : Draft, optional
            Comparison revision. When omitted, compare with the original loaded
            file, or empty text for a newly constructed/inline draft.

        Returns
        -------
        str
            Unified diff labeled before.malloy and after.malloy, or an empty string
            when the compared texts are equal.

        Examples
        --------
        >>> import pymalloy as pm
        >>> original = pm.draft().sources(values=pm.sql("SELECT 1 AS n"))
        >>> original.diff(original)
        ''
        """
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
        """Return a draft formatted by Malloy's formatter.

        Requires the headless compiler. Reparse the formatted source into editable
        syntax while retaining identity, captured imports, and managed data owners.

        Returns
        -------
        Draft
            A new formatted revision. Invalid syntax raises CompilationError.

        Examples
        --------
        >>> import pymalloy as pm
        >>> original = pm.draft("source: values is duckdb.sql('SELECT 1 AS n')")
        >>> formatted = original.format()
        >>> formatted.names
        ('values',)
        >>> formatted.format().text == formatted.text
        True
        """
        from pymalloy._headless.tooling import parse_syntax

        formatted = from_wire(
            parse_syntax(self.text, url=self.url, format=True),
            {value.reference: value for value in self.inputs},
        )
        if not isinstance(formatted, Syntax):
            raise TypeError("Compiler returned a scalar for a model document")
        return replace(self, syntax=formatted)

    @property
    def inputs(self) -> tuple[Input, ...]:
        """Return captured data owners, deduplicated and ordered by input name."""
        return self.syntax.inputs

    def _input(self) -> str | ModelSource:
        text = self.syntax.render(materialize=True)
        return (
            text
            if self.imports is None
            else ModelSource(self.url, text, self.imports, self.document_kind)
        )

    def save(self, path: str | Path | None = None, *, overwrite: bool = False) -> Path:
        r"""Write model text, detecting previously observed changes to a loaded file.

        Parameters
        ----------
        path : str or pathlib.Path, optional
            Destination. Defaults to the path of a file-backed draft. The parent
            directory must exist. A newly constructed draft needs an explicit path.
        overwrite : bool, default False
            Permit replacing an unrelated existing destination. Saving back to the
            loaded path instead checks that its text still matches the observed revision.

        Returns
        -------
        pathlib.Path
            Absolute path written. This saves source without compiling or validating it.

        Notes
        -----
        Drafts with captured Python data require export.bundle with a successful
        Validation, so the Parquet inputs accompany the model. The source-edit check
        is not a lock against concurrent writers.

        Examples
        --------
        >>> import pymalloy as pm
        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>> candidate = pm.draft("// model notes\n")
        >>> with TemporaryDirectory() as directory:
        ...     path = candidate.save(Path(directory) / "model.malloy")
        ...     print(path.read_text() == candidate.text)
        True
        """
        if self.inputs:
            raise ValueError(
                "Drafts with captured data require bundle(connection.validate(draft), directory)"
            )
        target = Path(path).resolve() if path is not None else self.path
        if target is None:
            raise ValueError("Choose a destination for this draft")
        return write_text(
            target,
            self.text,
            expected=self._original if target == self.path else None,
            overwrite=overwrite,
        )

    def to_python(
        self, *, name: str = "model", inputs: Mapping[str, str] | None = None
    ) -> str:
        """Emit editable Python constructors for this model revision.

        Parameters
        ----------
        name : str, default "model"
            Valid Python variable name for the reconstructed Draft.
        inputs : mapping of str to str, optional
            Captured input names mapped to Python expressions supplying their data,
            for example {"orders": "orders_frame"}. Those expressions must exist in
            the namespace executing the emitted code. They are trusted source code.

        Returns
        -------
        str
            Python source using pymalloy's public grammar. Supported syntax uses
            constructors, while unrepresented syntax remains literal. Scalar spelling
            may normalize. This does not recover the producer's dataframe pipeline.

        Examples
        --------
        >>> import pymalloy as pm
        >>> original = pm.draft().sources(values=pm.sql("SELECT 42 AS n"))
        >>> namespace = {}
        >>> exec(original.to_python(name="rebuilt"), namespace)
        >>> namespace["rebuilt"].text == original.text
        True
        """
        if not name.isidentifier() or keyword.iskeyword(name):
            raise ValueError("Choose a Python variable name")
        from pymalloy._authoring.python import python_source

        return python_source(self, name, inputs=inputs)


def draft(
    *parts: str | Source | View,
    url: str | None = None,
    imports: Mapping[str, str] | None = None,
) -> Draft:
    """Create an immutable model draft from syntax fragments or literal text.

    Parameters
    ----------
    *parts : str, Source, or View
        Ordered source text and fragments, concatenated without parsing.
        Use sources and queries to introduce editable named declarations.
    url : str, optional
        Absolute model identity used to resolve imports and report locations.
        Defaults to ``model.malloy`` in the current directory as a file URL.
    imports : mapping of str to str, optional
        Captured source text keyed by absolute URL. None permits live import
        resolution when compiled. A mapping supplies a closed import snapshot,
        so missing imports fail rather than reading from disk or the network.

    Returns
    -------
    Draft
        An editable value. Construction requires neither Deno nor a database.

    See Also
    --------
    read_model : Parse existing Malloy and recover its named editing scopes.
    connect : Own native compilation and execution.

    Examples
    --------
    >>> import pymalloy as pm
    >>> candidate = pm.draft().sources(values=pm.sql("SELECT 42 AS answer"))
    >>> candidate.names
    ('values',)
    """
    node = syntax(*parts, kind="document")
    return Draft(node, imports=imports) if url is None else Draft(node, url, imports)


def read_model(source: str | Path | ModelSource, *, url: str | None = None) -> Draft:
    """Parse existing Malloy into a lossless, editable draft.

    Parameters
    ----------
    source : str, pathlib.Path, or ModelSource
        Malloy text, a file Path, or a closed snapshot. A plain string is source
        text, even if it looks like a filename. Only plain model documents are
        supported for structured editing, not notebook/SQL document roots.
    url : str, optional
        Absolute identity for inline text. A Path or ModelSource supplies its own.

    Returns
    -------
    Draft
        Parsed source preserving authored text. Named declarations and fields
        can be replaced without changing unrelated syntax.

    Notes
    -----
    Requires ``pymalloy[headless]`` for the native Malloy parser. A file-backed
    unchanged draft saves byte-equivalent UTF-8 source and detects previously
    observed external edits. Parsing does not prove semantic validity.

    Examples
    --------
    >>> import pymalloy as pm
    >>> text = "source: orders is duckdb.sql('SELECT 2 AS amount') extend {measure: revenue is amount.sum()}"
    >>> original = pm.read_model(text)
    >>> revised = original.sources(orders=original["orders"].replace(
    ...     revenue=pm.col("amount").sum() * 2
    ... ))
    >>> original.text == text
    True
    >>> revised["orders"]["revenue"].equals(pm.col("amount").sum() * 2)
    True
    """
    from pymalloy._headless.tooling import parse_syntax

    identity, text, imports = resolve_source(source, url=url, root=Path.cwd())
    kind = (
        source.document_kind
        if isinstance(source, ModelSource)
        else resolve_document_kind(identity)
    )
    if kind != "model":
        raise ValueError("Structured authoring requires a .malloy document")
    path = source.resolve() if isinstance(source, Path) else None
    parsed = from_wire(
        parse_syntax(text, url=identity),
        {value.reference: value for value in source.inputs}
        if isinstance(source, ModelSource)
        else None,
    )
    if not isinstance(parsed, Syntax):
        raise TypeError("Compiler returned a scalar for a model document")
    return Draft(parsed, identity, imports, path, text if path is not None else None)
