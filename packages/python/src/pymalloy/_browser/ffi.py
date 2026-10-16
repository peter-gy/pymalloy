"""Load the packaged browser runtime and translate its owned JSON values."""

from __future__ import annotations

import hashlib
import importlib
import math
import sys
from importlib.resources import files
from typing import Any

import msgspec

from pymalloy.analysis import Diagnostic
from pymalloy.errors import CompilationError, PyMalloyError

_factory: Any = None


def require_browser() -> None:
    if sys.platform != "emscripten":
        raise ImportError(
            "browser.connect() requires Python running in Pyodide. "
            "Use pymalloy.connect() for native Python execution."
        )


def factory() -> Any:
    global _factory
    require_browser()
    if _factory is None:
        assets = files("pymalloy").joinpath("_assets/pyodide")
        bundle = assets.joinpath("runtime.js").read_bytes()
        manifest = msgspec.json.decode(
            assets.joinpath("runtime.manifest.json").read_bytes()
        )
        if hashlib.sha256(bundle).hexdigest() != manifest["bundleSha256"]:
            raise ImportError(
                "The packaged PyMalloy browser runtime digest differs from its manifest. "
                "Reinstall the PyMalloy wheel."
            )
        run_js = importlib.import_module("pyodide.code").run_js
        run_js(bundle.decode("utf-8"))
        _factory = run_js("globalThis.__pymalloy_browser")
    return _factory


def controller() -> Any:
    return importlib.import_module("js").AbortController.new()


def budget(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError("Operation timeout must be finite and positive")
    return float(value)


def encode(value: Any) -> str:
    return msgspec.json.encode(value).decode()


def domain_error(error: Exception) -> Exception:
    detail = getattr(getattr(error, "js_error", None), "pymalloyError", None)
    if not isinstance(detail, str):
        return error
    payload = msgspec.json.decode(detail)
    if payload["kind"] == "tooling":
        return CompilationError(
            payload["message"],
            diagnostics=msgspec.convert(
                payload.get("diagnostics", []), tuple[Diagnostic, ...], strict=True
            ),
        )
    return PyMalloyError(payload["message"])
