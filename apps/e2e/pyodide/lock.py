from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import tomllib
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

ROOT = Path(__file__).resolve().parents[3]
RUNTIME_PATH = Path(__file__).with_name("runtime.json")


def validate_runtime(version: str, runtime: dict) -> None:
    index = f"https://cdn.jsdelivr.net/pyodide/v{version}/full/"
    if runtime["indexURL"] != index:
        raise ValueError("indexURL must select the declared Pyodide release")
    required_files = {
        "pyodide.mjs",
        "pyodide.asm.mjs",
        "pyodide.asm.wasm",
        "python_stdlib.zip",
        "pyodide-lock.json",
    }
    if runtime["files"].keys() != required_files:
        raise ValueError("files must pin the Pyodide core runtime")
    for digest in runtime["files"].values():
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("core runtime files must declare SHA-256 digests")


def validate_lock(version: str, runtime: dict, lock: dict) -> None:
    validate_runtime(version, runtime)
    index = runtime["indexURL"]
    info = lock["info"]
    if (
        info["python"] != runtime["pythonVersion"]
        or info["arch"] != "wasm32"
        or info["abi_version"] != runtime["abiVersion"]
    ):
        raise ValueError(
            "lock must match the declared Python version and wasm32 architecture"
        )
    packages = lock["packages"]
    requirements = runtime["requirements"]
    metadata = tomllib.loads((ROOT / "packages/python/pyproject.toml").read_text())
    environment = default_environment()
    environment.update(
        os_name="posix",
        platform_system="Emscripten",
        sys_platform="emscripten",
        platform_machine="wasm32",
        python_version=".".join(runtime["pythonVersion"].split(".")[:2]),
        python_full_version=runtime["pythonVersion"],
    )
    project_requirements = [
        Requirement(value) for value in metadata["project"]["dependencies"]
    ]
    direct = {
        canonicalize_name(requirement.name): requirement
        for requirement in project_requirements
        if requirement.marker is None or requirement.marker.evaluate(environment)
    }
    if direct.keys() != requirements.keys():
        raise ValueError(
            "runtime requirements must match the browser wheel dependencies"
        )
    for name, required in requirements.items():
        if name not in packages or packages[name]["version"] != required:
            raise ValueError(f"{name} must be locked to {required}")
        if required not in direct[name].specifier:
            raise ValueError(
                f"{name}=={required} does not satisfy the wheel dependency"
            )
    if "micropip" not in packages:
        raise ValueError("lock must include micropip")
    reachable = set()
    pending = [*requirements, "micropip"]
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        if name not in packages:
            raise ValueError(f"unlocked dependency: {name}")
        reachable.add(name)
        pending.extend(packages[name]["depends"])
    if reachable != packages.keys():
        raise ValueError(
            "lock contains packages outside the browser dependency closure"
        )
    for name, package in packages.items():
        if (
            canonicalize_name(name) != name
            or canonicalize_name(package["name"]) != name
        ):
            raise ValueError(f"invalid package name: {name}")
        if re.fullmatch(r"[0-9a-f]{64}", package["sha256"]) is None:
            raise ValueError(f"{name} must declare a SHA-256 digest")
        url = urlsplit(package["file_name"])
        if url.scheme != "https" or url.netloc not in {
            "cdn.jsdelivr.net",
            "files.pythonhosted.org",
        }:
            raise ValueError(f"unsupported wheel source for {name}")
        if url.query or url.fragment:
            raise ValueError(f"wheel URL must identify an immutable archive: {name}")
        if url.netloc == "cdn.jsdelivr.net" and not package["file_name"].startswith(
            index
        ):
            raise ValueError(
                f"{name} must come from Pyodide {version}: {package['file_name']}"
            )
        filename = Path(url.path).name
        wheel_name, wheel_version, _, tags = parse_wheel_filename(filename)
        if wheel_name != name or str(wheel_version) != package["version"]:
            raise ValueError(
                f"wheel identity differs from {name}=={package['version']}"
            )
        python_version = tuple(map(int, runtime["pythonVersion"].split(".")[:2]))
        platforms = [f"pyemscripten_{runtime['abiVersion']}_wasm32"]
        interpreter = "cp" + "".join(map(str, python_version))
        supported = set(
            cpython_tags(python_version, abis=[interpreter], platforms=platforms)
        )
        supported.update(compatible_tags(python_version, interpreter, platforms))
        if tags.isdisjoint(supported):
            raise ValueError(f"wheel has an incompatible runtime tag: {filename}")


def generate(version: str, runtime: dict) -> dict:
    validate_runtime(version, runtime)
    with tempfile.TemporaryDirectory(prefix="pymalloy-pyodide-lock-") as directory:
        work = Path(directory)
        for filename, digest in runtime["files"].items():
            with urlopen(runtime["indexURL"] + filename, timeout=30) as response:
                content = response.read()
            if hashlib.sha256(content).hexdigest() != digest:
                raise ValueError(
                    f"Pyodide runtime archive does not match its digest: {filename}"
                )
            (work / filename).write_bytes(content)
        (work / "runtime.json").write_text(json.dumps({"version": version, **runtime}))
        subprocess.run(
            ["node", str(RUNTIME_PATH.with_name("resolve.mjs")), str(work)],
            check=True,
            timeout=180,
        )
        return json.loads((work / "pylock.json").read_text())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lock the supported Pyodide dependency runtime."
    )
    parser.add_argument(
        "--check", action="store_true", help="Validate the committed lock offline."
    )
    args = parser.parse_args()
    matrix = json.loads(RUNTIME_PATH.read_text())
    if (
        not matrix["hosts"]
        or set(matrix["hosts"].values()) != matrix["runtimes"].keys()
    ):
        raise ValueError("each host must select a declared Pyodide runtime")
    outputs = {}
    for version, runtime in matrix["runtimes"].items():
        if runtime["lockFile"] != f"pylock.{version}.json":
            raise ValueError("lockFile must identify the declared Pyodide runtime")
        path = RUNTIME_PATH.with_name(runtime["lockFile"])
        lock = (
            json.loads(path.read_text()) if args.check else generate(version, runtime)
        )
        validate_lock(version, runtime, lock)
        outputs[path] = lock
        print(f"Pyodide {version} dependency lock is valid")
    if not args.check:
        for path, lock in outputs.items():
            path.write_text(json.dumps(lock, indent=2) + "\n")
            print(f"Updated {path.relative_to(ROOT)}")
        subprocess.run(
            ["pnpm", "exec", "vp", "fmt", *map(str, outputs)],
            cwd=ROOT,
            check=True,
            timeout=60,
        )


if __name__ == "__main__":
    main()
