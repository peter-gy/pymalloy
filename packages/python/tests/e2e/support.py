"""Subprocess helpers for installed environments and exported notebooks."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
ASSETS = REPO / "packages" / "python" / "src" / "pymalloy" / "_assets"


def create_venv(path: Path) -> Path:
    subprocess.run(
        ["uv", "venv", "--python", "3.12", str(path)],
        check=True,
        timeout=120,
    )
    return path


def pip_install(venv: Path, *packages: str) -> None:
    subprocess.run(
        ["uv", "pip", "install", "--python", str(venv / "bin" / "python"), *packages],
        check=True,
        timeout=300,
    )


def isolated_env(venv: Path) -> dict[str, str]:
    env = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSAFEPATH",
        "UV_PROJECT_ENVIRONMENT",
    ):
        env.pop(name, None)
    env["PYTHONPATH"] = ""
    env["VIRTUAL_ENV"] = str(venv)
    env["PATH"] = os.pathsep.join((str(venv / "bin"), env.get("PATH", "")))
    return env


def run_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: float = 60,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def run_in_venv(
    venv: Path,
    *args: str,
    cwd: Path,
    timeout: float = 60,
) -> subprocess.CompletedProcess[str]:
    return run_command(
        [str(venv / "bin" / args[0]), *args[1:]],
        cwd=cwd,
        env=isolated_env(venv),
        timeout=timeout,
    )


def run_to_completion(
    command: list[str],
    *,
    cwd: Path,
    timeout: float,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        raise AssertionError(
            f"{command[0]} did not exit within {timeout}s\nstdout:\n{stdout}\nstderr:\n{stderr}"
        ) from None
    return subprocess.CompletedProcess(command, process.returncode or 0, stdout, stderr)
