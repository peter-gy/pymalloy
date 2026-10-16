from __future__ import annotations

import copy
import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ROOT = ROOT / "apps/e2e/pyodide"
VALIDATE_LOCK = runpy.run_path(str(RUNTIME_ROOT / "lock.py"))["validate_lock"]


@pytest.fixture
def locked_runtime():
    matrix = json.loads((RUNTIME_ROOT / "runtime.json").read_text())
    version = matrix["hosts"]["standalone"]
    runtime = matrix["runtimes"][version]
    return (
        version,
        runtime,
        json.loads((RUNTIME_ROOT / runtime["lockFile"]).read_text()),
    )


def test_pyodide_lock_satisfies_browser_wheel_dependencies(locked_runtime):
    version, runtime, lock = locked_runtime
    VALIDATE_LOCK(version, runtime, lock)


def test_pyodide_lock_requires_complete_transitive_dependencies(locked_runtime):
    version, runtime, lock = locked_runtime
    del lock["packages"]["comm"]
    with pytest.raises(ValueError, match="unlocked dependency: comm"):
        VALIDATE_LOCK(version, runtime, lock)


def test_pyodide_lock_rejects_packages_outside_the_dependency_closure(locked_runtime):
    version, runtime, lock = locked_runtime
    lock["packages"]["unused"] = copy.deepcopy(lock["packages"]["comm"])
    with pytest.raises(ValueError, match="outside the browser dependency closure"):
        VALIDATE_LOCK(version, runtime, lock)


@pytest.mark.parametrize(
    "filename",
    [
        "msgspec-0.20.0-cp314-cp314-manylinux_2_28_x86_64.whl",
        "msgspec-0.20.0-cp313-cp313-pyemscripten_2025_0_wasm32.whl",
    ],
)
def test_pyodide_lock_rejects_incompatible_binary_wheels(locked_runtime, filename):
    version, runtime, lock = locked_runtime
    lock["packages"]["msgspec"]["file_name"] = (
        "https://files.pythonhosted.org/packages/" + filename
    )
    with pytest.raises(ValueError, match="incompatible runtime tag"):
        VALIDATE_LOCK(version, runtime, lock)


def test_pyodide_lock_requires_package_hashes(locked_runtime):
    version, runtime, lock = locked_runtime
    lock["packages"]["anywidget"]["sha256"] = "invalid"
    with pytest.raises(ValueError, match="anywidget must declare a SHA-256 digest"):
        VALIDATE_LOCK(version, runtime, lock)


def test_pyodide_lock_requires_the_pinned_runtime(locked_runtime):
    version, runtime, lock = locked_runtime
    version = "314.0.6"
    with pytest.raises(
        ValueError, match="indexURL must select the declared Pyodide release"
    ):
        VALIDATE_LOCK(version, runtime, lock)


def test_pyodide_lock_requires_browser_dependency_roots(locked_runtime):
    version, runtime, lock = locked_runtime
    del runtime["requirements"]["msgspec"]
    with pytest.raises(ValueError, match="must match the browser wheel dependencies"):
        VALIDATE_LOCK(version, runtime, lock)


def test_pyodide_lock_requires_python_abi_alignment(locked_runtime):
    version, runtime, lock = locked_runtime
    lock["info"]["abi_version"] = "2025_0"
    with pytest.raises(ValueError, match="must match the declared Python version"):
        VALIDATE_LOCK(version, runtime, lock)


def test_pyodide_lock_requires_the_observed_python_patch(locked_runtime):
    version, runtime, lock = locked_runtime
    lock["info"]["python"] = "3.14.0"
    with pytest.raises(ValueError, match="must match the declared Python version"):
        VALIDATE_LOCK(version, runtime, lock)
