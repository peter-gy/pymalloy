"""Check the Pixi Rust toolchain, source policy, and dependency audit."""

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
    parser.add_argument("command", choices=["tools", "check", "test", "audit"])
    options = parser.parse_args()
    workspace = tomllib.loads(
        (ROOT.parents[1] / "pixi.toml").read_text(encoding="utf-8")
    )
    rust = workspace["feature"]["native"]["dependencies"]["rust"]
    if not rust.startswith("=="):
        raise RuntimeError("The Pixi manifest must pin an exact Rust version")
    tools = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))["package"][
        "metadata"
    ]["pymalloy"]["rust-tools"]
    environment = dict(os.environ)
    environment.setdefault("CARGO_BUILD_JOBS", "2")
    for name in ("cargo", "rustc"):
        if tool_version(name, environment) != rust.removeprefix("=="):
            raise RuntimeError(f"Run pixi install --locked to provide {name} {rust}")
    if options.command == "tools":
        if sys.platform == "win32":
            missing = [
                name for name in ("cl", "link", "rc") if shutil.which(name) is None
            ]
            if missing:
                raise RuntimeError(
                    "Install Visual Studio Build Tools with the repository's .vsconfig "
                    f"and reopen the Pixi environment. Missing tools: {', '.join(missing)}"
                )
        elif sys.platform == "darwin":
            subprocess.run(
                ["xcrun", "--show-sdk-path"],
                check=True,
                capture_output=True,
                text=True,
            )
        for name, version in tools.items():
            if tool_version(name, environment) != version:
                raise RuntimeError(
                    f"Run pixi install --locked to provide {name} {version}"
                )
    elif options.command == "check":
        run(["cargo", "fmt", "--check"], environment)
        from native_archive import prepare

        os.environ.update(environment)
        environment.update(prepare([]))
        run(
            ["cargo", "clippy", "--locked", "--all-targets", "--", "-D", "warnings"],
            environment,
        )
    elif options.command == "test":
        from native_archive import prepare

        os.environ.update(environment)
        environment.update(prepare([]))
        run(["cargo", "test", "--locked", "--lib"], environment)
    elif options.command == "audit":
        for name in ("cargo-deny", "cargo-shear"):
            if tool_version(name, environment) != tools[name]:
                raise RuntimeError(
                    f"Run pixi install --locked to provide {name} {tools[name]}"
                )
        run(["cargo", "shear", "--deny-warnings"], environment)
        run(
            ["cargo", "deny", "--locked", "check", "advisories", "bans", "sources"],
            environment,
        )


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
