"""Run the package's pinned Rust setup, source checks, and dependency audit."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(args: list[str], environment: dict[str, str]) -> None:
    subprocess.run(args, cwd=ROOT, env=environment, check=True)


def tool_version(name: str, environment: dict[str, str]) -> str | None:
    executable = shutil.which(name, path=environment["PATH"])
    if executable is None:
        return None
    result = subprocess.run(
        [executable, "--version"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    match = re.search(r"\b\d+\.\d+\.\d+\b", result.stdout)
    return match.group() if match else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["toolchain", "tools", "setup", "check", "test", "audit"]
    )
    parser.add_argument("--audit", action="store_true", help="Install audit tools too")
    parser.add_argument("--github-env", type=Path)
    options = parser.parse_args()
    toolchain = tomllib.loads((ROOT / "rust-toolchain.toml").read_text())["toolchain"]
    tools = tomllib.loads((ROOT / "Cargo.toml").read_text())["package"]["metadata"][
        "pymalloy"
    ]["rust-tools"]
    environment = dict(os.environ, RUSTUP_TOOLCHAIN=toolchain["channel"])
    environment.setdefault("CARGO_BUILD_JOBS", "2")
    if options.command in {"toolchain", "setup"}:
        run(
            [
                "rustup",
                "toolchain",
                "install",
                toolchain["channel"],
                "--profile",
                toolchain["profile"],
                "--component",
                ",".join(toolchain["components"]),
            ],
            environment,
        )
    cargo = subprocess.check_output(
        ["rustup", "which", "--toolchain", toolchain["channel"], "cargo"],
        cwd=ROOT,
        env=environment,
        text=True,
    ).strip()
    toolchain_bin = str(Path(cargo).parent)
    cargo_bin = str(Path(environment.get("CARGO_HOME", Path.home() / ".cargo")) / "bin")
    environment["PATH"] = os.pathsep.join(
        [cargo_bin, toolchain_bin, environment.get("PATH", "")]
    )
    if options.github_env:
        with options.github_env.open("a") as output:
            output.write(f"RUSTUP_TOOLCHAIN={toolchain['channel']}\n")
        with Path(environment["GITHUB_PATH"]).open("a") as output:
            output.write(f"{toolchain_bin}\n{cargo_bin}\n")
    if options.command in {"tools", "setup"}:
        selected = tools if options.audit else {"cargo-about": tools["cargo-about"]}
        for name, version in selected.items():
            if tool_version(name, environment) == version:
                continue
            args = [cargo, "install", name, "--version", version, "--locked"]
            if name == "cargo-about":
                args.extend(["--features", "cli"])
            run(args, environment)
    elif options.command == "check":
        run([cargo, "fmt", "--check"], environment)
        from native_archive import prepare

        os.environ.update(environment)
        environment.update(prepare([]))
        run(
            [cargo, "clippy", "--locked", "--all-targets", "--", "-D", "warnings"],
            environment,
        )
    elif options.command == "test":
        from native_archive import prepare

        os.environ.update(environment)
        environment.update(prepare([]))
        run([cargo, "test", "--locked", "--lib"], environment)
    elif options.command == "audit":
        for name in ("cargo-deny", "cargo-shear"):
            if tool_version(name, environment) != tools[name]:
                raise RuntimeError(
                    "Install the pinned Rust audit tools with "
                    "python packages/python/rust_tools.py setup --audit"
                )
        run([cargo, "shear", "--deny-warnings"], environment)
        run([cargo, "deny", "--locked", "check"], environment)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
