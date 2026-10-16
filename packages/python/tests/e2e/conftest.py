import os
import subprocess
from pathlib import Path

import pytest
from support import ASSETS, REPO, create_venv, pip_install


def _require_assets() -> None:
    marker = ASSETS / "widget" / "index.js"
    if not marker.is_file() or marker.stat().st_size == 0:
        pytest.skip(
            "packages/python/src/pymalloy/_assets is missing. "
            "Run pnpm build before the installed-wheel tests."
        )


@pytest.fixture(scope="session")
def distribution(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    _require_assets()
    configured = os.environ.get("PYMALLOY_DIST_DIR")
    out = (
        Path(configured).resolve()
        if configured
        else tmp_path_factory.mktemp("pymalloy-dist")
    )
    if configured is None:
        subprocess.run(
            [
                "uv",
                "build",
                "--package",
                "pymalloy",
                "--no-sources",
                "--out-dir",
                str(out),
            ],
            cwd=REPO,
            check=True,
            timeout=1800,
        )
    wheels = sorted(out.glob("pymalloy-*-cp312-abi3-*.whl"))
    archives = sorted(out.glob("pymalloy-*.tar.gz"))
    if len(wheels) != 1 or len(archives) != 1:
        raise AssertionError(
            f"expected one wheel and one sdist, found {wheels} and {archives}"
        )
    return wheels[0], archives[0]


@pytest.fixture(scope="session")
def browser_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    _require_assets()
    out = tmp_path_factory.mktemp("browser-dist")
    subprocess.run(
        [
            "uv",
            "run",
            "--frozen",
            "--only-group",
            "release",
            "python",
            "-m",
            "hatchling",
            "build",
            "--target",
            "wheel",
            "--directory",
            str(out),
        ],
        cwd=REPO / "packages" / "python",
        env={
            **os.environ,
            "UV_PROJECT_ENVIRONMENT": str(
                tmp_path_factory.mktemp("browser-build-env") / "venv"
            ),
        },
        check=True,
        timeout=180,
    )
    wheels = list(out.glob("pymalloy-*-py3-none-any.whl"))
    if len(wheels) != 1:
        raise AssertionError(f"expected one browser wheel, found {wheels}")
    return wheels[0]


@pytest.fixture(scope="session")
def native_venv(
    tmp_path_factory: pytest.TempPathFactory, distribution: tuple[Path, Path]
):
    wheel, _archive = distribution
    venv = create_venv(tmp_path_factory.mktemp("native-venv") / "venv")
    pip_install(venv, str(wheel))
    return venv


@pytest.fixture(scope="session")
def sdist_wheel(
    tmp_path_factory: pytest.TempPathFactory, distribution: tuple[Path, Path]
):
    _wheel, archive = distribution
    out = tmp_path_factory.mktemp("from-sdist")
    environment = os.environ.copy()
    if os.name != "nt":
        tools = tmp_path_factory.mktemp("source-build-tools")
        for name in ("node", "deno"):
            command = tools / name
            command.write_text("#!/bin/sh\nexit 97\n")
            command.chmod(0o755)
        environment["PATH"] = os.pathsep.join((str(tools), environment.get("PATH", "")))
    subprocess.run(
        ["uv", "build", "--wheel", str(archive), "--out-dir", str(out)],
        env=environment,
        check=True,
        timeout=1800,
    )
    wheels = sorted(out.glob("pymalloy-*.whl"))
    if len(wheels) != 1:
        raise AssertionError(
            f"expected one wheel rebuilt from the sdist, found {wheels}"
        )
    return wheels[0]


@pytest.fixture(scope="session")
def sdist_venv(tmp_path_factory: pytest.TempPathFactory, sdist_wheel: Path):
    venv = create_venv(tmp_path_factory.mktemp("sdist-venv") / "venv")
    pip_install(venv, str(sdist_wheel))
    return venv
