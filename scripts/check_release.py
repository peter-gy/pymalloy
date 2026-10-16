"""Validate release versions, annotated tags, and the complete distribution set."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tarfile
import tomllib
import zipfile
from email.message import Message
from email.parser import BytesParser
from pathlib import Path

from packaging.requirements import Requirement
from packaging.tags import Tag, parse_tag
from packaging.utils import parse_sdist_filename, parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]


def release_version(root: Path) -> str:
    package = root / "packages/python"
    project = tomllib.loads((package / "pyproject.toml").read_text())["project"]
    version = project["version"]
    cargo = tomllib.loads((package / "Cargo.toml").read_text())["package"]
    lock = tomllib.loads((package / "Cargo.lock").read_text())["package"]
    native = next(entry for entry in lock if entry["name"] == cargo["name"])
    if version != cargo["version"] or version != native["version"]:
        raise ValueError("Python, Cargo, and Cargo.lock package versions must agree")
    return version


def check_tag(root: Path, tag: str, version: str) -> None:
    if (
        re.fullmatch(r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", tag)
        is None
    ):
        raise ValueError("release tags use vX.Y.Z")
    if tag != f"v{version}":
        raise ValueError(f"pymalloy {version} does not match tag {tag}")
    reference = f"refs/tags/{tag}"

    def git(*arguments: str) -> str:
        return subprocess.check_output(["git", *arguments], cwd=root, text=True).strip()

    if git("cat-file", "-t", reference) != "tag":
        raise ValueError(f"release tag {tag} must be annotated")
    if git("rev-parse", f"{reference}^{{commit}}") != git("rev-parse", "HEAD"):
        raise ValueError(f"release tag {tag} must identify the checked-out commit")


def _metadata(data: bytes, version: str) -> Message:
    metadata = BytesParser().parsebytes(data)
    if metadata["Name"] != "pymalloy" or metadata["Version"] != version:
        raise ValueError(
            "distribution metadata must identify the release package and version"
        )
    return metadata


def check_distributions(root: Path, directory: Path, version: str) -> None:
    manifest = json.loads((root / "packages/python/native-archives.json").read_text())
    macos = manifest["macosDeploymentTarget"].replace(".", "_")
    platforms = {
        "x86_64-unknown-linux-gnu": "manylinux_2_28_x86_64",
        "aarch64-unknown-linux-gnu": "manylinux_2_28_aarch64",
        "x86_64-apple-darwin": f"macosx_{macos}_x86_64",
        "aarch64-apple-darwin": f"macosx_{macos}_arm64",
        "x86_64-pc-windows-msvc": "win_amd64",
    }
    expected = {platforms[target] for target in manifest["targets"]} | {
        "browser",
        "source",
    }
    actual: set[str] = set()
    dependencies: set[Requirement] | None = None
    for path in sorted(directory.iterdir()):
        if path.name.endswith(".tar.gz"):
            name, archive_version = parse_sdist_filename(path.name)
            kind = "source"
            with tarfile.open(path) as archive:
                member = archive.extractfile(f"pymalloy-{version}/PKG-INFO")
                if member is None:
                    raise ValueError(f"{path.name}: missing source metadata")
                _metadata(member.read(), version)
        elif path.suffix == ".whl":
            name, archive_version, build, tags = parse_wheel_filename(path.name)
            if build:
                raise ValueError(f"{path.name}: release wheels use the package version")
            pure = tags == {Tag("py3", "none", "any")}
            if pure:
                kind = "browser"
            else:
                if any(tag.interpreter != "cp312" or tag.abi != "abi3" for tag in tags):
                    raise ValueError(
                        f"{path.name}: native wheels require the Python 3.12 stable ABI"
                    )
                native_platforms = {tag.platform for tag in tags}
                if len(native_platforms) != 1 or not native_platforms <= set(
                    platforms.values()
                ):
                    raise ValueError(f"{path.name}: unexpected native platform tags")
                kind = next(iter(native_platforms))
            with zipfile.ZipFile(path) as archive:
                prefix = f"pymalloy-{version}.dist-info"
                metadata = _metadata(archive.read(f"{prefix}/METADATA"), version)
                wheel = BytesParser().parsebytes(archive.read(f"{prefix}/WHEEL"))
                if {
                    tag
                    for value in wheel.get_all("Tag", [])
                    for tag in parse_tag(value)
                } != tags:
                    raise ValueError(
                        f"{path.name}: wheel metadata tags differ from its filename"
                    )
                if wheel["Root-Is-Purelib"] != str(pure).lower():
                    raise ValueError(
                        f"{path.name}: wheel purity differs from its runtime"
                    )
                extensions = [
                    member
                    for member in archive.namelist()
                    if member.endswith((".so", ".pyd"))
                ]
                if len(extensions) != (0 if pure else 1) or any(
                    not member.startswith("pymalloy/_native.") for member in extensions
                ):
                    raise ValueError(
                        f"{path.name}: unexpected native extension payload"
                    )
                requirements = {
                    Requirement(value)
                    for value in metadata.get_all("Requires-Dist", [])
                }
                if dependencies is not None and requirements != dependencies:
                    raise ValueError(
                        f"{path.name}: runtime dependencies differ between wheels"
                    )
                dependencies = requirements
        else:
            raise ValueError(f"unexpected release file: {path.name}")
        if name != "pymalloy" or str(archive_version) != version:
            raise ValueError(f"{path.name}: expected pymalloy {version}")
        if kind in actual:
            raise ValueError(f"duplicate release artifact: {kind}")
        actual.add(kind)
    if actual != expected:
        raise ValueError(
            f"release artifacts differ: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag")
    parser.add_argument("--distributions", type=Path)
    arguments = parser.parse_args()
    try:
        version = release_version(ROOT)
        if arguments.tag:
            check_tag(ROOT, arguments.tag, version)
        if arguments.distributions:
            check_distributions(ROOT, arguments.distributions, version)
    except (
        ValueError,
        KeyError,
        OSError,
        StopIteration,
        subprocess.CalledProcessError,
    ) as error:
        raise SystemExit(f"Release validation failed: {error}") from error
    print(version)


if __name__ == "__main__":
    main()
