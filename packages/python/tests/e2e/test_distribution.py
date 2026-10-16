import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.tags import parse_tag
from packaging.utils import parse_wheel_filename

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(1800)]


@pytest.fixture
def native_source(tmp_path: Path, distribution: tuple[Path, Path]) -> Path:
    _wheel, archive_path = distribution
    with tarfile.open(archive_path) as archive:
        archive.extractall(tmp_path, filter="data")
    return next(tmp_path.glob("pymalloy-*/pyproject.toml")).parent


def _prepare_metadata(
    source: Path, metadata: Path, args: list[str]
) -> subprocess.CompletedProcess[str]:
    metadata.mkdir()
    return subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--python",
            sys.executable,
            "--with",
            "maturin==1.11.5",
            "python",
            "-c",
            (
                "import build_backend, sys; "
                "build_backend.prepare_metadata_for_build_wheel("
                "sys.argv[1], {'maturin.build-args': sys.argv[2:]})"
            ),
            str(metadata),
            *args,
        ],
        cwd=source,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def test_native_and_browser_wheels_share_package_metadata(
    distribution: tuple[Path, Path], browser_wheel: Path
):
    native_wheel, _archive = distribution
    metadata = []
    for wheel in (native_wheel, browser_wheel):
        with zipfile.ZipFile(wheel) as archive:
            name = next(
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            )
            metadata.append(BytesParser().parsebytes(archive.read(name)))
    for field in (
        "Name",
        "Version",
        "Requires-Python",
        "Provides-Extra",
    ):
        assert sorted(metadata[0].get_all(field, [])) == sorted(
            metadata[1].get_all(field, [])
        ), field
    assert {
        Requirement(value) for value in metadata[0].get_all("Requires-Dist", [])
    } == {Requirement(value) for value in metadata[1].get_all("Requires-Dist", [])}


def test_native_wheel_remaps_rust_build_paths(distribution: tuple[Path, Path]):
    wheel, _archive = distribution
    with zipfile.ZipFile(wheel) as archive:
        binary = archive.read(
            next(
                name
                for name in archive.namelist()
                if name.startswith("pymalloy/_native.")
                and name.endswith((".so", ".pyd"))
            )
        )
    for spelling in {str(Path.home()), Path.home().as_posix()}:
        assert (
            re.search(re.escape(spelling.encode()) + rb"[^\x00\n]*\.rs", binary) is None
        )
    checkout = Path(__file__).resolve().parents[4]
    for spelling in {str(checkout), checkout.as_posix()}:
        assert spelling.encode() not in binary, (
            f"Build checkout embedded in {wheel.name}"
        )


@pytest.mark.parametrize(
    "platform", [None, "riscv64-unknown-linux", "wasm32-pyodide2025"]
)
def test_installer_selects_runtime_artifact(
    tmp_path: Path,
    distribution: tuple[Path, Path],
    browser_wheel: Path,
    platform: str | None,
):
    native_wheel, _archive = distribution
    index = tmp_path / "wheels"
    index.mkdir()
    for wheel in (native_wheel, browser_wheel):
        shutil.copy2(wheel, index / wheel.name)
    target = tmp_path / "installed"
    command = [
        "uv",
        "pip",
        "install",
        "--target",
        str(target),
        "--no-deps",
        "--no-index",
        "--find-links",
        str(index),
        "--only-binary",
        ":all:",
        "--python-version",
        "3.13",
    ]
    if platform:
        command.extend(("--python-platform", platform))
    command.append("pymalloy")
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stderr
    native_modules = [
        path
        for path in (target / "pymalloy").glob("_native*")
        if path.suffix in {".so", ".pyd"}
    ]
    assert bool(native_modules) is (platform is None)
    assert (target / "pymalloy/_assets/widget/anywidget.json").is_file()
    assert (target / "pymalloy/_assets/agent/plugin.json").is_file()
    runtime = target / "pymalloy/_assets/pyodide/runtime.js"
    manifest = json.loads(runtime.with_name("runtime.manifest.json").read_text())
    assert hashlib.sha256(runtime.read_bytes()).hexdigest() == manifest["bundleSha256"]
    assert (target / "pymalloy/_assets/pyodide/runtime.LICENSE.txt").is_file()


def test_source_archive_contains_native_build_inputs(distribution: tuple[Path, Path]):
    _wheel, archive_path = distribution
    with tarfile.open(archive_path) as archive:
        paths = {
            Path(name).relative_to(Path(name).parts[0]).as_posix()
            for name in archive.getnames()
        }
    assert {
        "Cargo.toml",
        "Cargo.lock",
        "build.rs",
        "rust-toolchain.toml",
        "build_backend.py",
        "native_archive.py",
        "native-archives.json",
        "rust/lib.rs",
        "pyproject.toml",
        "src/pymalloy/_assets/compiler.js",
        "src/pymalloy/_assets/compiler.manifest.json",
        "src/pymalloy/_assets/compiler.LICENSE.txt",
        "src/pymalloy/_assets/native.LICENSE.txt",
        "src/pymalloy/_assets/native.manifest.json",
        "src/pymalloy/_assets/native.runtime.json",
        "src/pymalloy/_assets/widget/anywidget.json",
        "src/pymalloy/_assets/agent/plugin.json",
    } <= paths
    assert all(
        not ({"node_modules", "target", "__pycache__"} & set(Path(path).parts))
        and Path(path).suffix not in {".so", ".pyd", ".pyc"}
        for path in paths
    )


def test_source_build_rejects_v8_archive_digest_mismatch(
    tmp_path: Path, native_source: Path
):
    payload = tmp_path / "v8.a.gz"
    payload.write_bytes(b"invalid-v8")
    manifest_path = native_source / "native-archives.json"
    manifest = json.loads(manifest_path.read_text())
    for target in manifest["targets"].values():
        target["archive"] = {
            "url": payload.as_uri(),
            "sha256": "0" * 64,
            "size": payload.stat().st_size,
        }
    manifest_path.write_text(json.dumps(manifest))
    result = subprocess.run(
        [
            "uv",
            "build",
            "--wheel",
            str(native_source),
            "--out-dir",
            str(tmp_path / "wheel"),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode != 0
    assert "V8 input failed SHA-256 verification" in result.stderr


@pytest.mark.parametrize(
    "feature_args",
    [
        ["--features", "deno_core/v8_enable_pointer_compression"],
        ["--features=deno_core/v8_enable_pointer_compression"],
        ["-Fdeno_core/v8_enable_pointer_compression"],
        ["--all-features"],
        ["--no-default-features"],
    ],
)
def test_source_metadata_rejects_compiler_feature_selection(
    tmp_path: Path, native_source: Path, feature_args: list[str]
):
    result = _prepare_metadata(native_source, tmp_path / "metadata", feature_args)
    assert result.returncode != 0
    assert "fixed V8 features" in result.stderr


def test_source_metadata_resolves_before_native_archive_download(
    tmp_path: Path, native_source: Path
):
    manifest_path = native_source / "native-archives.json"
    manifest = json.loads(manifest_path.read_text())
    for target in manifest["targets"].values():
        for key in ("archive", "binding"):
            target[key]["url"] = (tmp_path / "unavailable-v8").as_uri()
    manifest_path.write_text(json.dumps(manifest))
    metadata = tmp_path / "metadata"
    result = _prepare_metadata(native_source, metadata, [])
    assert result.returncode == 0, result.stderr
    wheel = BytesParser().parsebytes(next(metadata.glob("*/WHEEL")).read_bytes())
    assert wheel["Root-Is-Purelib"] == "false"
    if sys.platform == "darwin":
        for tag in wheel.get_all("Tag"):
            match = re.search(r"macosx_(\d+)_(\d+)_", tag)
            assert match is not None, tag
            assert tuple(map(int, match.groups())) >= (12, 0)


@pytest.mark.parametrize("deployment_target", [None, "13.1", "11.0"])
def test_source_build_exports_macos_deployment_target(
    tmp_path: Path, native_source: Path, deployment_target: str | None
):
    payload = tmp_path / "verified-v8"
    payload.write_bytes(b"verified-native-input")
    manifest_path = native_source / "native-archives.json"
    manifest = json.loads(manifest_path.read_text())
    target = manifest["targets"]["aarch64-apple-darwin"]
    for key in ("archive", "binding"):
        target[key] = {
            "url": payload.as_uri(),
            "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
            "size": payload.stat().st_size,
        }
    manifest_path.write_text(json.dumps(manifest))
    environment = os.environ.copy()
    environment.pop("MACOSX_DEPLOYMENT_TARGET", None)
    if deployment_target:
        environment["MACOSX_DEPLOYMENT_TARGET"] = deployment_target
    exported = tmp_path / "native-env"
    result = subprocess.run(
        [
            sys.executable,
            "native_archive.py",
            "archive",
            "--target",
            "aarch64-apple-darwin",
            "--github-env",
            str(exported),
        ],
        cwd=native_source,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if deployment_target == "11.0":
        assert result.returncode != 0
        assert "MACOSX_DEPLOYMENT_TARGET >= 12.0" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        values = dict(line.split("=", 1) for line in exported.read_text().splitlines())
        assert values["MACOSX_DEPLOYMENT_TARGET"] == (deployment_target or "12.0")


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS wheel metadata")
def test_native_wheel_matches_v8_macos_deployment_floor(
    tmp_path: Path, distribution: tuple[Path, Path]
):
    wheel, _archive = distribution
    _name, _version, _build, tags = parse_wheel_filename(wheel.name)
    for tag in tags:
        match = re.fullmatch(r"macosx_(\d+)_(\d+)_(?:arm64|x86_64)", tag.platform)
        assert match is not None, tag
        assert tuple(map(int, match.groups())) >= (12, 0)
    with zipfile.ZipFile(wheel) as archive:
        metadata_path = next(
            name for name in archive.namelist() if name.endswith(".dist-info/WHEEL")
        )
        metadata = BytesParser().parsebytes(archive.read(metadata_path))
        assert {
            tag for value in metadata.get_all("Tag") for tag in parse_tag(value)
        } == tags
        module = next(
            name
            for name in archive.namelist()
            if name.startswith("pymalloy/_native.") and name.endswith(".so")
        )
        extension = tmp_path / "_native.so"
        extension.write_bytes(archive.read(module))
    result = subprocess.run(
        ["otool", "-l", str(extension)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    versions = re.findall(r"\bminos\s+(\d+)\.(\d+)", result.stdout)
    assert versions
    assert all(tuple(map(int, version)) >= (12, 0) for version in versions)
