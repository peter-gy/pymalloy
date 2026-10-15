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
    out = tmp_path_factory.mktemp("pymalloy-dist")
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
        timeout=180,
    )
    wheels = sorted(out.glob("pymalloy-*.whl"))
    archives = sorted(out.glob("pymalloy-*.tar.gz"))
    if len(wheels) != 1 or len(archives) != 1:
        raise AssertionError(
            f"expected one wheel and one sdist, found {wheels} and {archives}"
        )
    return wheels[0], archives[0]


@pytest.fixture(scope="session")
def base_venv(
    tmp_path_factory: pytest.TempPathFactory, distribution: tuple[Path, Path]
):
    wheel, _archive = distribution
    venv = create_venv(tmp_path_factory.mktemp("base-venv") / "venv")
    pip_install(venv, str(wheel))
    return venv


@pytest.fixture(scope="session")
def headless_venv(
    tmp_path_factory: pytest.TempPathFactory, distribution: tuple[Path, Path]
):
    wheel, _archive = distribution
    venv = create_venv(tmp_path_factory.mktemp("headless-venv") / "venv")
    pip_install(venv, f"{wheel}[headless]")
    return venv


@pytest.fixture(scope="session")
def sdist_wheel(
    tmp_path_factory: pytest.TempPathFactory, distribution: tuple[Path, Path]
):
    _wheel, archive = distribution
    out = tmp_path_factory.mktemp("from-sdist")
    subprocess.run(
        ["uv", "build", "--wheel", str(archive), "--out-dir", str(out)],
        check=True,
        timeout=180,
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
    pip_install(venv, f"{sdist_wheel}[headless]")
    return venv
