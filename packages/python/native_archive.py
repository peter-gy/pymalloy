from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any


def _download(spec: dict[str, Any]) -> Path:
    cache = (
        Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo"))
        / "pymalloy-v8"
        / spec["sha256"]
    )
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / spec["url"].rsplit("/", 1)[1]
    if destination.is_file():
        with destination.open("rb") as cached:
            if hashlib.file_digest(cached, "sha256").hexdigest() == spec["sha256"]:
                return destination
    print(f"Fetching verified V8 input {destination.name}", file=sys.stderr)
    temporary = None
    try:
        with (
            urllib.request.urlopen(spec["url"], timeout=120) as response,
            tempfile.NamedTemporaryFile(dir=cache, delete=False) as output,
        ):
            temporary = Path(output.name)
            digest = hashlib.sha256()
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > spec["size"]:
                    raise RuntimeError(
                        f"V8 input exceeds its pinned size: {spec['url']}"
                    )
                digest.update(chunk)
                output.write(chunk)
        if size != spec["size"] or digest.hexdigest() != spec["sha256"]:
            raise RuntimeError(f"V8 input failed SHA-256 verification: {spec['url']}")
        temporary.replace(destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prepare(
    args: list[str], target: str | None = None, *, download: bool = True
) -> dict[str, str]:
    root = Path(__file__).resolve().parent
    for index, arg in enumerate(args):
        if arg == "--":
            break
        if arg in {
            "--features",
            "-F",
            "--all-features",
            "--no-default-features",
        } or arg.startswith(("--features=", "-F")):
            raise RuntimeError(
                "PyMalloy builds use the fixed V8 features in native-archives.json"
            )
        if arg == "--target":
            target = args[index + 1]
        elif arg.startswith("--target="):
            target = arg.partition("=")[2]
    target = target or os.environ.get("CARGO_BUILD_TARGET")
    if target is None:
        version = subprocess.check_output(["rustc", "-vV"], encoding="utf-8", cwd=root)
        target = next(
            line.removeprefix("host: ")
            for line in version.splitlines()
            if line.startswith("host: ")
        )
    pinned = json.loads((root / "native-archives.json").read_text(encoding="utf-8"))
    if target not in pinned["targets"]:
        raise RuntimeError(
            f"PyMalloy native builds require a pinned V8 target. Target {target!r} has no archive in native-archives.json."
        )
    flags = (
        os.environ["CARGO_ENCODED_RUSTFLAGS"].split("\x1f")
        if "CARGO_ENCODED_RUSTFLAGS" in os.environ
        else os.environ.get("RUSTFLAGS", "").split()
    )
    linker = os.environ.get(f"CARGO_TARGET_{target.upper().replace('-', '_')}_LINKER")
    if (
        target.endswith("-linux-gnu")
        and linker
        and "-conda-linux-gnu-" in Path(linker).name
    ):
        specs = subprocess.check_output(
            [linker, "-print-file-name=builtin.specs"], encoding="utf-8", cwd=root
        ).strip()
        if not Path(specs).is_file():
            raise RuntimeError("The Conda compiler must provide its builtin GCC specs")
        # Builtin specs keep environment paths out of the wheel. GNU ld resolves
        # the compiler's sysroot linker scripts through the matching toolchain.
        for flag in (
            "-Clink-arg=-specs=builtin.specs",
            "-Clink-arg=-fuse-ld=bfd",
        ):
            if flag not in flags:
                flags.append(flag)
    elif target.endswith("-apple-darwin"):
        prefix = os.environ.get("CONDA_PREFIX")
        compiler = shutil.which(linker or "cc")
        if (
            prefix
            and compiler
            and Path(compiler).resolve().is_relative_to(Path(prefix).resolve())
            and Path(compiler).resolve().name.startswith("clang")
        ):
            # The Apple SDK supplies wheel dependencies. Conda's default Clang
            # configuration selects libraries from its environment directory.
            flag = "-Clink-arg=--no-default-config"
            if flag not in flags:
                flags.append(flag)
    sysroot = subprocess.check_output(
        ["rustc", "--print", "sysroot"], encoding="utf-8", cwd=root
    ).strip()
    prefixes = {}
    for path, replacement in (
        (Path.home(), "build-home"),
        (Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo")), "cargo"),
        (root, "pymalloy"),
        (Path(sysroot), "rust-toolchain"),
    ):
        for spelling in {str(path), path.as_posix()}:
            prefixes[spelling] = replacement
    for prefix, replacement in sorted(
        prefixes.items(), key=lambda item: (len(item[0]), item[0])
    ):
        flag = f"--remap-path-prefix={prefix}={replacement}"
        if flag not in flags:
            flags.append(flag)
    environment = {
        "CARGO_ENCODED_RUSTFLAGS": "\x1f".join(flag for flag in flags if flag)
    }
    if target.endswith("-apple-darwin"):
        minimum = pinned["macosDeploymentTarget"]
        deployment_target = os.environ.get("MACOSX_DEPLOYMENT_TARGET", minimum)
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", deployment_target):
            raise RuntimeError(
                f"MACOSX_DEPLOYMENT_TARGET must be a macOS version such as {minimum}"
            )
        version = tuple(map(int, deployment_target.split(".")))
        floor = tuple(map(int, minimum.split(".")))
        if version + (0,) * (3 - len(version)) < floor + (0,) * (3 - len(floor)):
            raise RuntimeError(
                f"PyMalloy's pinned V8 archives require MACOSX_DEPLOYMENT_TARGET >= {minimum}, got {deployment_target!r}"
            )
        environment["MACOSX_DEPLOYMENT_TARGET"] = deployment_target
    metadata = json.loads(
        subprocess.check_output(
            [
                "cargo",
                "metadata",
                "--locked",
                "--format-version",
                "1",
                "--filter-platform",
                target,
            ],
            encoding="utf-8",
            cwd=root,
        )
    )
    v8 = [package for package in metadata["packages"] if package["name"] == "v8"]
    if len(v8) != 1 or v8[0]["version"] != pinned["v8Version"]:
        raise RuntimeError("Update native-archives.json for the locked V8 version")
    features = next(
        node["features"]
        for node in metadata["resolve"]["nodes"]
        if node["id"] == v8[0]["id"]
    )
    if sorted(features) != pinned["features"]:
        raise RuntimeError("Update native-archives.json for the selected V8 features")
    if os.environ.get("V8_FORCE_DEBUG") in {"1", "true", "yes"} or os.environ.get(
        "V8_FROM_SOURCE"
    ) in {"1", "true", "yes"}:
        raise RuntimeError(
            "PyMalloy builds use the verified release V8 archives in native-archives.json"
        )
    files = pinned["targets"][target]
    if download:
        environment.update(
            RUSTY_V8_ARCHIVE=str(_download(files["archive"])),
            RUSTY_V8_SRC_BINDING_PATH=str(_download(files["binding"])),
        )
    os.environ.update(environment)
    return environment


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["archive"])
    parser.add_argument("--target", required=True)
    parser.add_argument("--github-env", type=Path)
    parser.add_argument("--shell-env", type=Path)
    options = parser.parse_args()
    environment = prepare([], target=options.target)
    if options.github_env:
        with options.github_env.open("a") as output:
            for key, value in environment.items():
                output.write(f"{key}={value}\n")
    if options.shell_env:
        options.shell_env.write_text(
            "".join(
                f"export {key}={shlex.quote(value)}\n"
                for key, value in environment.items()
            )
        )
