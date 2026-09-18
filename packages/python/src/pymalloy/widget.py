from __future__ import annotations

import json
import math
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import anywidget
import traitlets as t

from pymalloy._source import ModelSource
from pymalloy.browser import Runtime


class _Snapshot(t.Dict):
    def get(self, obj: Any, cls: Any = None) -> dict[str, Any]:
        return deepcopy(cast(dict[str, Any], super().get(obj, cls)))


def _empty_state(status: str = "idle") -> dict[str, Any]:
    return {
        "status": status,
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
    state: dict[str, Any] = {key: deepcopy(wire.get(key)) for key in _empty_state()}
    if not isinstance(state["status"], str) or state["status"] not in {
        "idle",
        "loading",
        "ready",
        "error",
        "closed",
    }:
        raise t.TraitError("Browser state has an invalid status")
    for name in ("queries", "columns"):
        if not isinstance(state[name], list) or not all(
            isinstance(item, str) for item in state[name]
        ):
            raise t.TraitError(f"Browser state {name} must be a list of strings")
    for name in ("sql", "error"):
        if state[name] is not None and not isinstance(state[name], str):
            raise t.TraitError(f"Browser state {name} must be a string or None")
    state["diagnostics"] = _diagnostics(state["diagnostics"])
    rows = state["rows"]
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise t.TraitError("Browser state rows must be a list of records")
    paths = wire.get("integer_paths", [])
    if not isinstance(paths, list):
        raise t.TraitError("Browser integer paths must be a list")
    for path in paths:
        container, key = _result_path(rows, path)
        value = container[key]
        if (
            not isinstance(value, str)
            or not value.isascii()
            or not value.removeprefix("-").isdecimal()
        ):
            raise t.TraitError("Browser integer path must address an integer string")
        container[key] = int(value)
    numbers = wire.get("number_paths", [])
    if not isinstance(numbers, list):
        raise t.TraitError("Browser number paths must be a list")
    for item in numbers:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("value"), str)
            or item["value"] not in {"nan", "inf", "-inf"}
        ):
            raise t.TraitError("Browser number paths must describe NaN or infinity")
        container, key = _result_path(rows, item.get("path"))
        if container[key] is not None:
            raise t.TraitError("Browser number path must address a null placeholder")
        container[key] = float(item["value"])
    return state


def _diagnostics(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise t.TraitError("Browser diagnostics must be a list")
    for item in value:
        if not isinstance(item, dict):
            raise t.TraitError("Browser diagnostics must contain records")
        if not all(
            isinstance(item.get(key), str) for key in ("code", "message", "severity")
        ):
            raise t.TraitError(
                "Browser diagnostic code, message, and severity must be strings"
            )
        if item["severity"] not in {"error", "warning", "debug"}:
            raise t.TraitError(
                "Browser diagnostic severity must be error, warning, or debug"
            )
        if "replacement" not in item or not (
            item["replacement"] is None or isinstance(item["replacement"], str)
        ):
            raise t.TraitError(
                "Browser diagnostic replacement must be a string or None"
            )
        if "data" not in item or "error_tag" not in item:
            raise t.TraitError("Browser diagnostics require data and error_tag fields")
        if item["error_tag"] is not None and not isinstance(item["error_tag"], str):
            raise t.TraitError("Browser diagnostic error_tag must be a string or None")
        if "location" not in item:
            raise t.TraitError("Browser diagnostics must include a location or None")
        location = item["location"]
        if location is not None:
            if (
                not isinstance(location, dict)
                or not isinstance(location.get("url"), str)
                or not isinstance(location.get("range"), dict)
            ):
                raise t.TraitError(
                    "Browser diagnostic locations require a URL and range"
                )
            positions = []
            for name in ("start", "end"):
                point = location["range"].get(name)
                if not isinstance(point, dict) or not all(
                    type(point.get(key)) is int and point[key] >= 0
                    for key in ("line", "character")
                ):
                    raise t.TraitError(
                        "Browser diagnostic ranges require nonnegative line and character positions"
                    )
                positions.append((point["line"], point["character"]))
            if positions[1] < positions[0]:
                raise t.TraitError("Browser diagnostic range ends before it starts")
        try:
            json.dumps(item, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise t.TraitError(
                "Browser diagnostics must contain finite JSON values"
            ) from error
    return value


def _result_path(rows: list[dict[str, Any]], path: Any) -> tuple[Any, Any]:
    if not isinstance(path, list) or not path:
        raise t.TraitError("Browser value paths must address a result value")
    container: Any = rows
    try:
        for index, key in enumerate(path):
            if not (
                isinstance(container, dict)
                and isinstance(key, str)
                or isinstance(container, list)
                and type(key) is int
                and 0 <= key < len(container)
            ):
                raise ValueError
            value = container[key]
            if index == len(path) - 1:
                return container, key
            container = value
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise t.TraitError("Browser value path must address a result value") from error
    raise t.TraitError("Browser value path must address a result value")


def _encode_givens(values: dict[str, Any]) -> tuple[dict[str, Any], list[list[Any]]]:
    paths: list[list[Any]] = []

    def encode(value: Any, path: list[Any]) -> Any:
        if type(value) is int and abs(value) > 2**53 - 1:
            paths.append(path)
            return str(value)
        if isinstance(value, dict):
            return {key: encode(item, [*path, key]) for key, item in value.items()}
        if isinstance(value, list):
            return [encode(item, [*path, index]) for index, item in enumerate(value)]
        return value

    return encode(values, []), paths


class Malloy(anywidget.AnyWidget):
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
    _state = t.Dict(default_value=None, allow_none=True).tag(sync=True)

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
            raise t.TraitError("The widget is closed. Create a new Malloy widget")
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
        givens, integer_paths = _encode_givens(self.givens)
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
                    "definition_revision": self._definition_revision,
                    "query": self.query,
                    "givens": givens,
                    "integer_paths": integer_paths,
                },
            )

    @t.validate("_state")
    def _validate_state(self, proposal: t.Bunch) -> dict[str, Any] | None:
        wire = proposal.value
        if not wire or self._closed or wire.get("revision") != self._revision:
            return self._state
        if type(wire.get("revision")) is not int:
            raise t.TraitError("Browser state revision must be an integer")
        self._decoded_state = _decode_state(wire)
        return deepcopy(wire)

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
            change.old = deepcopy(change.old)
            change.new = deepcopy(change.new)
        super().notify_change(change)

    def close(self) -> None:
        """Close the widget and release its browser connection."""
        if getattr(self, "_closed", True):
            return
        self._closed = True
        self.set_trait("state", _empty_state("closed"))
        super().close()
