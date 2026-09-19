from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import traitlets as t
from anywidget_bundle import Bundle, BundledWidget
from msgspec import ValidationError, convert, to_builtins

from pymalloy._authoring.draft import Draft
from pymalloy._authoring.syntax import Fragment
from pymalloy._model import DEFAULT_CONNECTION
from pymalloy._notebook import NotebookDisplay
from pymalloy._notebook.subject import Subject, describe
from pymalloy._protocol.givens import encode_givens
from pymalloy._protocol.records import (
    ActionRequest,
    DefinitionMetadata,
    Input,
    NotebookError,
    NotebookReply,
    NotebookRequest,
    NotebookResponse,
    State,
    WidgetAction,
    WidgetMessage,
)
from pymalloy._protocol.snapshot import freeze
from pymalloy.browser import Runtime


class _ImmutableMapping(t.Instance):
    def validate(self, obj: Any, value: Any) -> Mapping[str, Any]:
        return freeze(super().validate(obj, value))


def _empty_state(status: str = "idle") -> Mapping[str, Any]:
    return freeze(
        {
            "status": status,
            "result": None,
            "queries": [],
            "sql": None,
            "columns": [],
            "rows": [],
            "error": None,
            "diagnostics": [],
            "inspection": None,
        }
    )


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, (list, tuple)):
        for item in value:
            _json_value(item)
        return value
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _json_value(item)
        return value
    raise t.TraitError("Givens must contain finite JSON values with string keys")


def _decode_state(wire: dict[str, Any]) -> dict[str, Any]:
    from msgspec import ValidationError

    from pymalloy._protocol.codec import decode_state

    try:
        return decode_state(wire)
    except (ValidationError, ValueError, TypeError, KeyError) as error:
        raise t.TraitError(f"Invalid browser state: {error}") from error


class MalloyWidget(BundledWidget):
    r"""Inspect PyMalloy values and run queries in a notebook widget.

    Display in a notebook supporting anywidget, such as marimo or Jupyter.
    Browser execution uses ``pymalloy`` and DuckDB WebAssembly. A native Model
    or Query supplies its own Python execution context from ``pymalloy[headless]``.

    Parameters
    ----------
    source : str, Expr, Sort, Fragment, Draft, ModelSource, Model, Query, or Result
        Authored syntax, a complete model, a bound native query, or materialized
        results. Syntax shows its Malloy text, references and annotations.
        Complete drafts run in the browser. Native models and queries preview
        at most 20 rows on their existing Python connection, with a 30-second
        timeout. Results show up to 20 retained rows without executing SQL.
    files : mapping, optional
        Browser virtual names mapped to UTF-8 text, bytes, or {"url": "https://..."}.
        Remote files require browser-accessible URLs with suitable CORS headers.
    query : str, optional
        Inventory name to select. None uses the last run or sole available
        query, otherwise exposes query choices without executing a selection.
    givens : mapping, optional
        Finite JSON-compatible values for declared parameters: strings, numbers,
        booleans, nulls, lists and mappings. Unlike native execution, widget input
        validation does not accept Python Decimal, date or datetime objects.
    runtime : pymalloy.browser.Runtime, optional
        Explicit WebAssembly/worker asset URLs for the widget's lifetime.
        Omitted uses the bundled runtime's defaults, downloaded on first use.
    connection_name : str, default "duckdb"
        Malloy name for the browser's DuckDB connection. Fixed for its lifetime.
        Native models and queries supply their own connection name.
    auto_run : bool, default True
        Execute when a browser attaches or inputs change. Set False to inspect
        first and use the Check and Run buttons. Automatic notebook
        representations of PyMalloy values always use False. Captured dataframe
        inputs become Parquet at construction with True, or on the first Check
        or Run request with False.

    Attributes
    ----------
    state : read-only mapping
        status, queries, sql, columns, rows, result, inspection, error and
        diagnostics for the current input revision. Nested mappings are read-only
        and sequences are tuples. Read results after status becomes "ready".

    Notes
    -----
    Assign source, query, givens or files to trigger updates. Assign complete
    input mappings rather than mutating them. Observe ``state`` with traitlets
    for asynchronous readback. pymalloy.analysis.to_dict creates mutable copies.
    Construction alone does not execute anything until a browser view is attached.
    Call close when finished. New inputs supersede older in-flight results.
    Native models and queries remain owned by the caller. Closing their widget
    leaves the model and connection open. Isolated expressions and query clauses
    expose authored structure until composed into a model that supplies context.
    Native values reject browser-only files and runtime options. A bound Query
    accepts its own query name or None. Supply a Model to select other queries.

    Examples
    --------
    >>> import pymalloy as pm
    >>> widget = pm.MalloyWidget("run: duckdb.table('orders.csv') -> {select: amount}",
    ...     files={"orders.csv": "amount\n42\n"})
    >>> def receive(change):
    ...     if change.new["status"] == "ready":
    ...         print(change.new["rows"])
    >>> widget.observe(receive, names="state")
    >>> widget.state["status"]
    'idle'

    Display the widget as a notebook cell's output to start browser execution:

    >>> widget  # doctest: +SKIP

    Once finished, close it to release its resources:

    >>> widget.close()
    """

    bundle = Bundle(Path(__file__).with_name("_assets") / "widget")

    source: t.TraitType[str | NotebookDisplay, str | NotebookDisplay] = t.Union(
        [t.Unicode(), t.Instance(NotebookDisplay)]
    )
    auto_run = t.Bool(default_value=True)
    _request = t.Dict(default_value=None, allow_none=True).tag(sync=True)
    _transient = t.Bool(default_value=False, read_only=True).tag(sync=True)
    query = t.Unicode(default_value=None, allow_none=True).tag(sync=True)
    connection_name = t.Unicode(default_value=DEFAULT_CONNECTION, read_only=True)
    givens = _ImmutableMapping(Mapping, default_value=freeze({}))
    files = _ImmutableMapping(Mapping, default_value=freeze({}))
    runtime = t.Instance[Runtime | None](
        Runtime, default_value=None, allow_none=True, read_only=True
    )
    state = _ImmutableMapping(Mapping, default_value=_empty_state(), read_only=True)
    _runtime = t.Dict(default_value=None, allow_none=True, read_only=True).tag(
        sync=True
    )
    _definition = t.Dict(default_value=None, allow_none=True, read_only=True).tag(
        sync=True
    )
    _input = t.Dict(default_value=None, allow_none=True, read_only=True).tag(sync=True)
    _state = t.Dict(default_value=None, allow_none=True).tag(
        sync=True, echo_update=False
    )

    def __init__(
        self,
        source: str | NotebookDisplay,
        *,
        files: Mapping[str, Any] | None = None,
        query: str | None = None,
        givens: Mapping[str, Any] | None = None,
        runtime: Runtime | None = None,
        connection_name: str = DEFAULT_CONNECTION,
        auto_run: bool = True,
        _transient: bool = False,
    ) -> None:
        self._initializing = True
        self._closed = False
        self._views: set[str] = set()
        self._prepared = False
        self._dirty = True
        self._revision = 0
        self._definition_revision = 0
        self._accepted_wire: dict[str, Any] | None = None
        if not isinstance(connection_name, str) or not connection_name:
            raise t.TraitError("connection_name must be a nonempty string")
        if not isinstance(source, (str, NotebookDisplay)):
            raise t.TraitError(
                "Source must be Malloy text or a PyMalloy notebook value"
            )
        for name, value in (("files", files), ("givens", givens)):
            if value is not None and not isinstance(value, Mapping):
                raise t.TraitError(f"{name} must be a mapping")
        subject = (
            describe(source) if isinstance(source, str) else source._notebook_subject()
        )
        self._subject: Subject = subject
        super().__init__(
            source=source,
            auto_run=auto_run,
            files=dict(files) if files is not None else {},
            query=query,
            givens=dict(givens) if givens is not None else {},
        )
        try:
            self.set_trait("_transient", _transient)
            self.on_msg(self._view_message)
            self.set_trait(
                "connection_name", subject.connection_name or connection_name
            )
            self.set_trait("runtime", runtime)
            self.set_trait(
                "_runtime", runtime._bundles() if runtime is not None else None
            )
            self._initializing = False
            self._publish_input(definition_changed=True, subject=subject)
        except BaseException:
            self.close()
            raise

    @t.validate("source", "query", "files", "givens", "auto_run")
    def _validate_input(self, proposal: t.Bunch) -> Any:
        if self._closed:
            raise t.TraitError("The widget is closed. Create a new MalloyWidget")
        name, value = proposal.trait.name, proposal.value
        if name in {"source", "files"}:
            source = value if name == "source" else self.source
            files = value if name == "files" else self.files
            if isinstance(source, (Draft, Fragment)) and any(
                item.reference in files for item in source.inputs
            ):
                raise t.TraitError("Files cannot replace captured dataframe inputs")
            subject = (
                describe(source)
                if isinstance(source, str)
                else source._notebook_subject()
            )
            if subject.info.execution in {"python", "result"} and (
                files or self.runtime
            ):
                raise t.TraitError(
                    "files and runtime apply to browser sources. Native values use their existing Python context"
                )
        if name == "query" and value is not None and not value.strip():
            raise t.TraitError("Query must be a nonempty name or None")
        if name == "givens":
            return _json_value(value)
        if name == "files":
            if not isinstance(value, Mapping):
                raise t.TraitError("files must be a mapping")
            result: dict[str, bytes | dict[str, str]] = {}
            for key, item in value.items():
                if not isinstance(key, str) or not key or "\x00" in key:
                    raise t.TraitError("File names must be nonempty strings")
                if isinstance(item, str):
                    result[key] = item.encode("utf-8")
                elif isinstance(item, bytes):
                    result[key] = item
                elif isinstance(item, Mapping) and set(item) == {"url"}:
                    url = item["url"]
                    if not isinstance(url, str):
                        raise t.TraitError("File URLs must be strings")
                    try:
                        parsed = urlsplit(url)
                    except ValueError as error:
                        raise t.TraitError(
                            "File URLs must be absolute HTTP or HTTPS URLs"
                        ) from error
                    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                        raise t.TraitError(
                            "File URLs must be absolute HTTP or HTTPS URLs"
                        )
                    result[key] = {"url": url}
                else:
                    raise t.TraitError(
                        "Files must contain UTF-8 text, bytes, or URL descriptors"
                    )
            return freeze(result)
        return value

    @t.observe("source", "query", "files", "givens", "auto_run")
    def _input_changed(self, change: t.Bunch) -> None:
        if not self._initializing:
            self._publish_input(definition_changed=change.name in {"source", "files"})

    def _publish_input(
        self,
        *,
        definition_changed: bool = False,
        action: WidgetAction | None = None,
        subject: Subject | None = None,
    ) -> None:
        action = action or ("run" if self.auto_run else "inspect")
        self._dirty |= definition_changed
        if subject is None:
            subject = self._subject
            if self._dirty:
                subject = (
                    describe(self.source)
                    if isinstance(self.source, str)
                    else self.source._notebook_subject()
                )
        if subject.info.execution in {"python", "result"} and (
            self.files or self.runtime
        ):
            raise t.TraitError(
                "files and runtime apply to browser sources. Native values use their existing Python context"
            )
        prepared = self._prepared and not self._dirty
        definition_changed = self._dirty or (
            bool(subject.inputs) and action != "inspect" and not prepared
        )
        definition: dict[str, Any] = self._definition
        if definition_changed:
            files = {
                name: dict(item) if isinstance(item, Mapping) else item
                for name, item in self.files.items()
            }
            if action != "inspect":
                files.update(
                    (item.reference, item.materialize().path.read_bytes())
                    for item in subject.inputs
                )
                prepared = True
            metadata = DefinitionMetadata(
                revision=self._definition_revision + 1,
                connection_name=subject.connection_name or self.connection_name,
                source=subject.source,
                url=subject.url,
                document_kind=subject.document_kind,
                imports=dict(subject.imports) if subject.imports is not None else None,
                notebook=subject.info,
                queries=subject.queries,
            )
            definition = {**to_builtins(metadata), "files": files}
        inputs = Input(
            revision=self._revision + 1,
            definition_revision=definition["revision"],
            query=self.query,
            givens=encode_givens(self.givens),
            action=action,
        )
        # Materialization and encoding must succeed before publishing a revision.
        self._subject, self._prepared, self._dirty = subject, prepared, False
        self._revision = inputs.revision
        self._definition_revision = definition["revision"]
        with self.hold_sync():
            self.set_trait("state", _empty_state())
            if definition_changed:
                self.set_trait("_definition", definition)
            self.set_trait("_input", to_builtins(inputs))

    @t.observe("_request")
    def _requested(self, change: t.Bunch) -> None:
        request = change.new
        if self._closed or not request:
            return
        self.set_trait("_request", None)
        try:
            action = convert(request, ActionRequest, strict=True)
        except ValidationError:
            return
        if action.revision != self._revision:
            return
        try:
            self._publish_input(action=action.action)
        except Exception as error:  # noqa: BLE001 - Publish preparation failures to the requesting view.
            self.set_trait(
                "_state",
                to_builtins(
                    State(
                        revision=self._revision,
                        status="error",
                        queries=(),
                        result=None,
                        inspection=None,
                        error=str(error),
                        diagnostics=(),
                    )
                ),
            )

    def _view_message(self, _widget, content, buffers) -> None:
        try:
            message = convert(content, WidgetMessage, strict=True)
        except ValidationError:
            return
        if isinstance(message, NotebookRequest):
            response, output = self._perform(message.input, buffers)
            self.send(
                to_builtins(
                    NotebookReply(
                        kind="pymalloy-response", id=message.id, response=response
                    )
                ),
                buffers=output,
            )
            return
        if not self._transient:
            return
        if message.action == "mount":
            self._views.add(message.id)
        elif message.id in self._views:
            self._views.remove(message.id)
            if not self._views:
                self.close()

    def _perform(
        self, request: Input, buffers
    ) -> tuple[NotebookResponse, list[memoryview]]:
        if self._closed or to_builtins(request) != self._input or buffers:
            return NotebookError(
                message="The displayed revision is no longer current", diagnostics=()
            ), []
        try:
            return self._subject.perform(request)
        except Exception as error:  # noqa: BLE001 - Every comm request must receive a settled failure response.
            return NotebookError(
                message=str(error), diagnostics=getattr(error, "diagnostics", ())
            ), []

    @t.validate("_state")
    def _validate_state(self, proposal: t.Bunch) -> dict[str, Any] | None:
        wire = proposal.value
        if not wire or self._closed or wire.get("revision") != self._revision:
            return self._accepted_wire
        if type(wire.get("revision")) is not int:
            raise t.TraitError("Browser state revision must be an integer")
        # The decoder and resynchronization retain one detached result tree.
        accepted = to_builtins(wire)
        decoded = _decode_state(accepted)
        self._decoded_state = decoded
        self._accepted_wire = accepted
        return accepted

    @t.observe("_state")
    def _state_changed(self, change: t.Bunch) -> None:
        if (
            not self._closed
            and change.new
            and change.new.get("revision") == self._revision
        ):
            self.set_trait("state", self._decoded_state)

    def close(self) -> None:
        """Close the widget and release its browser resources when attached.

        Pending state becomes closed, and further input assignment is rejected.
        Repeated calls are safe. Retained immutable state snapshots remain readable.
        """
        if getattr(self, "_closed", True):
            return
        self._closed = True
        self.set_trait("state", _empty_state("closed"))
        super().close()
