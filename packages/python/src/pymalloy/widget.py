from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import anywidget
import traitlets as t
from msgspec import to_builtins

from pymalloy._authoring.draft import Draft
from pymalloy._model import DEFAULT_CONNECTION
from pymalloy._model.source import ModelSource
from pymalloy._protocol.givens import encode_givens
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


class MalloyWidget(anywidget.AnyWidget):
    r"""Run Malloy in a browser widget and observe results from Python.

    Display in a notebook supporting anywidget, such as marimo or Jupyter.
    Requires ``pymalloy``. Malloy and DuckDB WebAssembly run in the browser,
    so the widget itself requires neither Deno nor native Python DuckDB.

    Parameters
    ----------
    source : str, ModelSource, or Draft
        Model text, closed source snapshot, or symbolic draft. Captured Python
        inputs on a draft are materialized and sent as Parquet bytes.
    files : mapping, optional
        Virtual names mapped to UTF-8 text, bytes, or {"url": "https://..."}.
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
        Malloy name for this widget's DuckDB connection. Fixed for its lifetime.

    Attributes
    ----------
    state : read-only mapping
        status, queries, sql, columns, rows, result, error and diagnostics for
        the current input revision. Nested mappings are read-only and sequences
        are tuples. Read results after status becomes "ready".

    Notes
    -----
    Assign source, query, givens or files to trigger updates. Assign complete
    input mappings rather than mutating them. Observe ``state`` with traitlets
    for asynchronous readback. pymalloy.analysis.to_dict creates mutable copies.
    Construction alone does not execute anything until a browser view is attached.
    Call close when finished. New inputs supersede older in-flight results.

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

    _esm = Path(__file__).with_name("_assets") / "widget.js"
    _css = Path(__file__).with_name("_assets") / "widget.css"

    source = t.Union([t.Unicode(), t.Instance(ModelSource), t.Instance(Draft)])
    query = t.Unicode(default_value=None, allow_none=True).tag(sync=True)
    connection_name = t.Unicode(default_value=DEFAULT_CONNECTION, read_only=True)
    givens = _ImmutableMapping(Mapping, default_value=freeze({}))
    files = _ImmutableMapping(Mapping, default_value=freeze({}))
    runtime = t.Instance(Runtime, default_value=None, allow_none=True, read_only=True)
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
        source: str | ModelSource | Draft,
        *,
        files: Mapping[str, Any] | None = None,
        query: str | None = None,
        givens: Mapping[str, Any] | None = None,
        runtime: Runtime | None = None,
        connection_name: str = DEFAULT_CONNECTION,
    ) -> None:
        self._initializing = True
        self._closed = False
        self._revision = 0
        self._definition_revision = 0
        self._accepted_wire: dict[str, Any] | None = None
        if not isinstance(connection_name, str) or not connection_name:
            raise t.TraitError("connection_name must be a nonempty string")
        for name, value in (("files", files), ("givens", givens)):
            if value is not None and not isinstance(value, Mapping):
                raise t.TraitError(f"{name} must be a mapping")
        super().__init__(
            source=source,
            files=dict(files) if files is not None else {},
            query=query,
            givens=dict(givens) if givens is not None else {},
        )
        self.set_trait("connection_name", connection_name)
        self.set_trait("runtime", runtime)
        self.set_trait("_runtime", runtime._bundles() if runtime is not None else None)
        self._initializing = False
        self._publish_input(definition_changed=True)

    @t.validate("source", "query", "files", "givens")
    def _validate_input(self, proposal: t.Bunch) -> Any:
        if self._closed:
            raise t.TraitError("The widget is closed. Create a new MalloyWidget")
        name, value = proposal.trait.name, proposal.value
        if name in {"source", "files"}:
            source = value if name == "source" else self.source
            files = value if name == "files" else self.files
            if isinstance(source, Draft) and any(
                item.reference in files for item in source.inputs
            ):
                raise t.TraitError("Files cannot replace captured dataframe inputs")
        if name == "query" and value is not None and not value.strip():
            raise t.TraitError("Query must be a nonempty name or None")
        if name == "givens":
            return _json_value(value)
        if name == "files":
            result = {}
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

    @t.observe("source", "query", "files", "givens")
    def _input_changed(self, change: t.Bunch) -> None:
        if not self._initializing:
            self._publish_input(definition_changed=change.name in {"source", "files"})

    def _publish_input(self, *, definition_changed: bool = False) -> None:
        self._revision += 1
        givens = encode_givens(self.givens)
        self.set_trait("state", _empty_state())
        with self.hold_sync():
            if definition_changed:
                self._definition_revision += 1
                source = self.source
                files = {
                    name: dict(item) if isinstance(item, Mapping) else item
                    for name, item in self.files.items()
                }
                if isinstance(source, Draft):
                    for captured in source.inputs:
                        files[captured.reference] = (
                            captured.materialize().path.read_bytes()
                        )
                self.set_trait(
                    "_definition",
                    {
                        "revision": self._definition_revision,
                        "connectionName": self.connection_name,
                        "source": source.text
                        if isinstance(source, (ModelSource, Draft))
                        else source,
                        "url": source.url
                        if isinstance(source, (ModelSource, Draft))
                        else None,
                        "documentKind": source.document_kind
                        if isinstance(source, (ModelSource, Draft))
                        else "model",
                        "imports": dict(source.imports)
                        if isinstance(source, (ModelSource, Draft))
                        and source.imports is not None
                        else None,
                        "files": files,
                    },
                )
            self.set_trait(
                "_input",
                {
                    "revision": self._revision,
                    "definitionRevision": self._definition_revision,
                    "query": self.query,
                    "givens": givens,
                },
            )

    @t.validate("_state")
    def _validate_state(self, proposal: t.Bunch) -> dict[str, Any] | None:
        wire = proposal.value
        if not wire or self._closed or wire.get("revision") != self._revision:
            return self._accepted_wire
        if type(wire.get("revision")) is not int:
            raise t.TraitError("Browser state revision must be an integer")
        decoded = _decode_state(wire)
        accepted = to_builtins(wire)
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
