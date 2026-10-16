"""Shared package and runtime inputs for browser notebook hosts."""

from __future__ import annotations

import hashlib
import json
import os
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = "http://127.0.0.1:28443"


class StaticServer(ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True


def browser_wheel() -> Path:
    selected = os.environ.get("PYMALLOY_BROWSER_WHEEL")
    if selected and not Path(selected).is_absolute():
        raise ValueError("PYMALLOY_BROWSER_WHEEL must be an absolute path")
    wheels = (
        [Path(selected).resolve()]
        if selected
        else list((ROOT / "dist/browser").glob("*.whl"))
    )
    if len(wheels) != 1 or not wheels[0].name.endswith("-py3-none-any.whl"):
        raise ValueError(
            "Select one browser wheel with PYMALLOY_BROWSER_WHEEL or dist/browser"
        )
    wheel = wheels[0]
    if not wheel.is_file():
        raise FileNotFoundError(wheel)
    return wheel


def runtime_config(host: str = "jupyterlite") -> dict[str, object]:
    matrix = json.loads((Path(__file__).parent / "pyodide/runtime.json").read_text())
    return matrix["runtimes"][matrix["hosts"][host]]


def bootstrap(host: str = "jupyterlite") -> str:
    wheel = browser_wheel()
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    return f'''import json
import sys
import importlib.metadata
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import micropip
from pyodide.http import pyfetch

_response = await pyfetch("{ASSET_ROOT}/pyodide/{runtime_config(host)["lockFile"]}")
_lock = await _response.json()
_packages = [*_lock["packages"].values(), {{"file_name": "{ASSET_ROOT}/wheels/{wheel.name}", "sha256": "{digest}"}}]
with TemporaryDirectory() as _directory:
    _verified = []
    for _package in _packages:
        _download = await pyfetch(_package["file_name"])
        _data = await _download.bytes()
        if hashlib.sha256(_data).hexdigest() != _package["sha256"]:
            raise ValueError("Wheel SHA-256 mismatch: " + _package["file_name"])
        _path = Path(_directory) / _package["file_name"].rsplit("/", 1)[1]
        _path.write_bytes(_data)
        _verified.append("emfs:" + str(_path))
    await micropip.install(_verified, deps=False)
import pymalloy as pm
from pymalloy import browser
from pymalloy.analysis import to_dict
runtime = browser.Runtime(
    mvp=browser.Bundle(module="{ASSET_ROOT}/duckdb/duckdb-mvp.wasm", worker="{ASSET_ROOT}/duckdb/duckdb-browser-mvp.worker.js"),
    eh=browser.Bundle(module="{ASSET_ROOT}/duckdb/duckdb-eh.wasm", worker="{ASSET_ROOT}/duckdb/duckdb-browser-eh.worker.js"),
)
assert sys.platform == "emscripten", sys.platform
assert sys.version.split()[0] == {runtime_config(host)["pythonVersion"]!r}, sys.version
async with browser.connect(runtime=runtime) as connection:
    model = await connection.model("run: duckdb.sql('SELECT 42 AS answer') -> {{select: answer}}")
    assert (await model.query().run()).to_pylist() == [{{"answer": 42}}]
print("Browser wheel ready:", importlib.metadata.version("pymalloy"))
'''
