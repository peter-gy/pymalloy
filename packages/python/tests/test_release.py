import io
import json
import runpy
import subprocess
import tarfile
import zipfile
from email.message import EmailMessage
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CHECKS = runpy.run_path(str(ROOT / "scripts/check_release.py"))


@pytest.fixture
def project(tmp_path: Path) -> Path:
    package = tmp_path / "packages/python"
    package.mkdir(parents=True)
    (package / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n')
    (package / "Cargo.toml").write_text(
        '[package]\nname = "pymalloy-native"\nversion = "1.2.3"\n'
    )
    (package / "Cargo.lock").write_text(
        '[[package]]\nname = "pymalloy-native"\nversion = "1.2.3"\n'
    )
    (package / "native-archives.json").write_bytes(
        (ROOT / "packages/python/native-archives.json").read_bytes()
    )
    return tmp_path


def _metadata() -> bytes:
    message = EmailMessage()
    message["Metadata-Version"] = "2.4"
    message["Name"] = "pymalloy"
    message["Version"] = "1.2.3"
    message["Requires-Dist"] = "anywidget>=0.11"
    return message.as_bytes()


@pytest.fixture
def distributions(tmp_path: Path) -> Path:
    directory = tmp_path / "distributions"
    directory.mkdir()
    for tag in (
        "cp312-abi3-manylinux_2_28_x86_64",
        "cp312-abi3-manylinux_2_28_aarch64",
        "cp312-abi3-macosx_12_0_x86_64",
        "cp312-abi3-macosx_12_0_arm64",
        "cp312-abi3-win_amd64",
        "py3-none-any",
    ):
        wheel = EmailMessage()
        wheel["Wheel-Version"] = "1.0"
        wheel["Root-Is-Purelib"] = str(tag == "py3-none-any").lower()
        wheel["Tag"] = tag
        with zipfile.ZipFile(directory / f"pymalloy-1.2.3-{tag}.whl", "w") as archive:
            archive.writestr("pymalloy-1.2.3.dist-info/METADATA", _metadata())
            archive.writestr("pymalloy-1.2.3.dist-info/WHEEL", wheel.as_bytes())
            if tag != "py3-none-any":
                archive.writestr(
                    "pymalloy/_native.pyd"
                    if "win_" in tag
                    else "pymalloy/_native.abi3.so",
                    b"native",
                )
    with tarfile.open(directory / "pymalloy-1.2.3.tar.gz", "w:gz") as archive:
        info = tarfile.TarInfo("pymalloy-1.2.3/PKG-INFO")
        info.size = len(_metadata())
        archive.addfile(info, io.BytesIO(_metadata()))
    return directory


def test_release_versions_match_python_cargo_and_lock(project: Path):
    assert CHECKS["release_version"](project) == "1.2.3"
    (project / "packages/python/Cargo.lock").write_text(
        '[[package]]\nname = "pymalloy-native"\nversion = "1.2.4"\n'
    )
    with pytest.raises(ValueError, match="versions must agree"):
        CHECKS["release_version"](project)


def test_release_tags_identify_an_annotated_matching_commit(project: Path):
    def git(*arguments: str):
        return subprocess.run(
            [
                "git",
                "-c",
                "user.name=Release Test",
                "-c",
                "user.email=release@example.com",
                *arguments,
            ],
            cwd=project,
            capture_output=True,
            text=True,
            check=True,
        )

    git("init", "--quiet")
    git("add", ".")
    git("commit", "--quiet", "-m", "Package metadata")
    git("tag", "v1.2.3")
    with pytest.raises(ValueError, match="must be annotated"):
        CHECKS["check_tag"](project, "v1.2.3", "1.2.3")
    git("tag", "-d", "v1.2.3")
    git("tag", "-a", "v1.2.3", "-m", "Release 1.2.3")
    CHECKS["check_tag"](project, "v1.2.3", "1.2.3")
    with pytest.raises(ValueError, match="does not match"):
        CHECKS["check_tag"](project, "v1.2.4", "1.2.3")
    git("commit", "--allow-empty", "--quiet", "-m", "Later commit")
    with pytest.raises(ValueError, match="checked-out commit"):
        CHECKS["check_tag"](project, "v1.2.3", "1.2.3")


def test_release_contains_each_native_target_browser_and_source(
    project: Path, distributions: Path
):
    CHECKS["check_distributions"](project, distributions, "1.2.3")
    (distributions / "pymalloy-1.2.3-cp312-abi3-win_amd64.whl").unlink()
    with pytest.raises(ValueError, match="missing=.*win_amd64"):
        CHECKS["check_distributions"](project, distributions, "1.2.3")


def test_release_follows_the_verified_engine_target_inventory(
    project: Path, distributions: Path
):
    manifest_path = project / "packages/python/native-archives.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["targets"].pop("x86_64-pc-windows-msvc")
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="extra=.*win_amd64"):
        CHECKS["check_distributions"](project, distributions, "1.2.3")


@pytest.mark.parametrize(
    ("filename", "replacement", "message"),
    [
        (
            "pymalloy-1.2.3-cp312-abi3-win_amd64.whl",
            "pymalloy-1.2.4-cp312-abi3-win_amd64.whl",
            "expected pymalloy 1.2.3",
        ),
        (
            "pymalloy-1.2.3-cp312-abi3-win_amd64.whl",
            "pymalloy-1.2.3-cp314-cp314-win_amd64.whl",
            "Python 3.12 stable ABI",
        ),
        (
            "pymalloy-1.2.3-cp312-abi3-macosx_12_0_arm64.whl",
            "pymalloy-1.2.3-cp312-abi3-macosx_11_0_arm64.whl",
            "unexpected native platform",
        ),
    ],
)
def test_release_rejects_incompatible_wheel_identity(
    project: Path, distributions: Path, filename: str, replacement: str, message: str
):
    (distributions / filename).rename(distributions / replacement)
    with pytest.raises(ValueError, match=message):
        CHECKS["check_distributions"](project, distributions, "1.2.3")


def test_release_rejects_wheel_tags_that_differ_from_metadata(
    project: Path, distributions: Path
):
    path = distributions / "pymalloy-1.2.3-cp312-abi3-win_amd64.whl"
    with zipfile.ZipFile(path) as archive:
        payloads = {name: archive.read(name) for name in archive.namelist()}
    payloads["pymalloy-1.2.3.dist-info/WHEEL"] = (
        b"Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: cp314-cp314-win_amd64\n"
    )
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in payloads.items():
            archive.writestr(name, payload)
    with pytest.raises(ValueError, match="tags differ"):
        CHECKS["check_distributions"](project, distributions, "1.2.3")
