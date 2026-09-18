"""Shared corpus evidence and isolated worker execution."""

import hashlib
import json
import math
import os
import signal
import subprocess


def digest(rows, *, unordered=False, float_precision=None):
    def normalize(value):
        if isinstance(value, dict):
            return {
                "object": {key: normalize(item) for key, item in sorted(value.items())}
            }
        if isinstance(value, (tuple, list)):
            return [normalize(item) for item in value]
        if isinstance(value, float):
            if not math.isfinite(value):
                number = str(value)
            elif float_precision is not None:
                number = format(value, f".{float_precision}g")
            else:
                number = value.hex()
            return {"float": number}
        if value is None or isinstance(value, (str, bool, int)):
            return value
        return {type(value).__name__: str(value)}

    normalized = [normalize(row) for row in rows]
    if unordered:
        normalized.sort(key=lambda row: json.dumps(row, sort_keys=True))
    return hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()


def sample_paths(root, match=""):
    return sorted(
        path
        for path in root.rglob("*")
        if path.suffix in {".malloy", ".malloynb", ".malloysql"}
        and "node_modules" not in path.parts
        and match in str(path.relative_to(root))
    )


def checkout_revision(root):
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def run_worker(command, *, cwd, timeout):
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        return {"status": "timeout", "error": f"Sample exceeded {timeout} seconds"}
    if process.returncode:
        return {"status": "worker_failed", "error": stderr}
    try:
        record = json.loads(stdout)
    except json.JSONDecodeError as error:
        return {
            "status": "worker_failed",
            "error": f"Invalid worker response: {error}",
            "stdout": stdout,
            "stderr": stderr,
        }
    if not isinstance(record, dict) or "status" not in record:
        return {
            "status": "worker_failed",
            "error": "Worker response has no status",
            "stdout": stdout,
            "stderr": stderr,
        }
    return record
