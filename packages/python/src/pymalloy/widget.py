from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import anywidget
import traitlets as t

from pymalloy._givens import encode_givens
from pymalloy._snapshot import snapshot
from pymalloy._source import ModelSource
from pymalloy.browser import Runtime


class _Snapshot(t.Dict):
    def get(self, obj: Any, cls: Any = None) -> dict[str, Any]:
        return snapshot(cast(dict[str, Any], super().get(obj, cls)))


def _empty_state(status: str = "idle") -> dict[str, Any]:
    return {
        "status": status,
        "result": None,
        "queries": [],
        "sql": None,
        "columns": [],
        "rows": [],
        "error": None,
        "diagnostics": [],
    }


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return {key: _json_value(item) for key, item in value.items()}
    raise t.TraitError("Givens must contain finite JSON values with string keys")


def _decode_state(wire: dict[str, Any]) -> dict[str, Any]:
    from msgspec import ValidationError

    from pymalloy._wire import decode_state

    try:
        return decode_state(wire)
    except (ValidationError, ValueError, TypeError, KeyError) as error:
        raise t.TraitError(f"Invalid browser state: {error}") from error


class MalloyWidget(anywidget.AnyWidget):
    """Run a Malloy model in a browser widget.

    Assign `source`, `query`, `givens`, or `files` to run an updated model.
    Files map virtual names to UTF-8 text, bytes, or `{"url": "https://..."}`.
    `files` and `givens` return detached mappings. Assign a complete mapping
    to apply an update.
    `state` returns a detached snapshot with status, queries, SQL, columns, rows,
    diagnostics with source locations, and an error message. Observe `state`
    to receive browser result updates.
    """

    _esm = Path(__file__).with_name("_assets") / "widget.js"
    _css = Path(__file__).with_name("_assets") / "widget.css"

    source = t.Union([t.Unicode(), t.Instance(ModelSource)])
    query = t.Unicode(default_value=None, allow_none=True).tag(sync=True)
    givens = _Snapshot(default_value={})
    files = _Snapshot(default_value={})
    runtime = t.Instance(Runtime, default_value=None, allow_none=True, read_only=True)
    state = _Snapshot(default_value=_empty_state(), read_only=True)
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
        source: str | ModelSource,
        *,
        files: Mapping[str, Any] | None = None,
        query: str | None = None,
        givens: Mapping[str, Any] | None = None,
        runtime: Runtime | None = None,
    ) -> None:
        self._initializing = True
        self._closed = False
        self._revision = 0
        self._definition_revision = 0
        self._accepted_wire: dict[str, Any] | None = None
        for name, value in (("files", files), ("givens", givens)):
            if value is not None and not isinstance(value, Mapping):
                raise t.TraitError(f"{name} must be a mapping")
        super().__init__(
            source=source,
            files=dict(files) if files is not None else {},
            query=query,
            givens=dict(givens) if givens is not None else {},
        )
        self.set_trait("runtime", runtime)
        self.set_trait("_runtime", runtime._bundles() if runtime is not None else None)
        self._initializing = False
        self._publish_input(definition_changed=True)

    @t.validate("source", "query", "files", "givens")
    def _validate_input(self, proposal: t.Bunch) -> Any:
        if self._closed:
            raise t.TraitError("The widget is closed. Create a new MalloyWidget")
        name, value = proposal.trait.name, proposal.value
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
            return result
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
                self.set_trait(
                    "_definition",
                    {
                        "revision": self._definition_revision,
                        "source": source.text
                        if isinstance(source, ModelSource)
                        else source,
                        "url": source.url if isinstance(source, ModelSource) else None,
                        "imports": dict(source.imports)
                        if isinstance(source, ModelSource)
                        else None,
                        "files": self.files,
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
        accepted = snapshot(wire)
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

    def notify_change(self, change: t.Bunch) -> None:
        if change.name in {"state", "files", "givens"}:
            change = t.Bunch(change)
            if change.old is not t.Undefined:
                change.old = snapshot(change.old)
            change.new = snapshot(change.new)
        super().notify_change(change)

    def close(self) -> None:
        """Close the widget and release its browser connection."""
        if getattr(self, "_closed", True):
            return
        self._closed = True
        self.set_trait("state", _empty_state("closed"))
        super().close()
