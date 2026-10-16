"""Run the Python suite with each runtime dependency at its declared lower bound."""

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path
from tempfile import TemporaryDirectory

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    project = tomllib.loads(
        (ROOT / "packages/python/pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    floors = []
    for value in project["dependencies"]:
        requirement = Requirement(value)
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        bounds = [
            item.version for item in requirement.specifier if item.operator == ">="
        ]
        if len(bounds) != 1:
            raise ValueError(f"A dependency must declare one lower bound: {value}")
        floors.append(f"{requirement.name}=={bounds[0]}")
    print("Declared floors:", *floors, sep="\n", flush=True)

    with TemporaryDirectory(prefix="pymalloy-floors-") as directory:
        work = Path(directory)
        subprocess.run(
            [
                "uv",
                "build",
                "--package",
                "pymalloy",
                "--no-sources",
                "--wheel",
                "--out-dir",
                str(work / "native"),
            ],
            cwd=ROOT,
            check=True,
        )
        wheels = list((work / "native").glob("pymalloy-*-cp312-abi3-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"Expected one native wheel, found {wheels}")
        venv = work / "venv"
        subprocess.run(
            ["uv", "venv", "--quiet", "--python", "3.12", str(venv)],
            cwd=ROOT,
            check=True,
        )
        python = venv / "Scripts/python.exe" if os.name == "nt" else venv / "bin/python"
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--quiet",
                "--python",
                str(python),
                str(wheels[0]),
                *floors,
                "pytest",
                "pytest-timeout",
                "polars",
                "marimo[recommended]",
                "nbformat",
                "nbclient",
                "ipykernel",
            ],
            cwd=ROOT,
            check=True,
        )
        environment = dict(os.environ)
        environment["PATH"] = os.pathsep.join((str(python.parent), environment["PATH"]))
        subprocess.run(
            [str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=ROOT,
            env=environment,
            check=True,
        )


if __name__ == "__main__":
    main()
