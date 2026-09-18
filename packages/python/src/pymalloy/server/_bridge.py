from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import deno

from pymalloy.analysis import Diagnostic
from pymalloy.server._errors import BridgeError, CompilationError


class Bridge:
    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._stderr = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")  # noqa: SIM115 - owned until bridge.close()
        self._terminated = False
        self._sequence = 0

    @property
    def terminated(self) -> bool:
        return self._terminated

    def _start(self) -> subprocess.Popen[str]:
        if self._terminated:
            raise BridgeError("The Deno bridge is closed. Create a new Session.")
        if self._process is None:
            try:
                executable = deno.find_deno_bin()
            except FileNotFoundError:
                executable = shutil.which("deno")
            if executable is None:
                raise BridgeError(
                    "Deno executable not found. Install the project's dependencies."
                )
            path = Path(__file__).parents[1] / "_assets" / "bridge.mjs"
            if not path.is_file():
                raise BridgeError(
                    "Python bridge bundle is missing. Run pnpm build in the workspace."
                )
            self._process = subprocess.Popen(
                [
                    executable,
                    "run",
                    "--no-prompt",
                    "--allow-read",
                    "--allow-env",
                    "--no-config",
                    "--cached-only",
                    str(path),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr,
                text=True,
                encoding="utf-8",
            )
            if self._terminated:
                self._process.kill()
                raise BridgeError(
                    "The Deno bridge was interrupted. Create a new Session."
                )
        return self._process

    def request(
        self, request: dict[str, Any], describe: Callable[[str], list[dict[str, str]]]
    ) -> dict[str, Any]:
        try:
            process = self._start()
        except OSError as error:
            self.terminate()
            raise BridgeError(f"Could not start Deno: {error}") from error
        stdin, stdout = process.stdin, process.stdout
        assert stdin is not None and stdout is not None
        self._sequence += 1
        request_id = self._sequence

        def send(message: dict[str, Any]) -> None:
            stdin.write(json.dumps(message, allow_nan=False) + "\n")
            stdin.flush()

        try:
            send({**request, "id": request_id})
            while True:
                line = stdout.readline()
                if not line:
                    self._stderr.seek(0)
                    detail = self._stderr.read()[-4000:].strip()
                    raise BridgeError(
                        f"Deno bridge exited unexpectedly. {detail}".strip()
                    )
                response = json.loads(line)
                if not isinstance(response, dict):
                    raise BridgeError("Deno bridge response must be an object")
                if response.get("id") != request_id:
                    raise BridgeError("Deno bridge returned an unexpected request ID")
                kind = response.get("kind")
                if kind == "schema":
                    try:
                        payload = {"columns": describe(response["sql"])}
                    except Exception as error:  # noqa: BLE001 - report host schema errors to Malloy's compiler
                        payload = {"error": str(error)}
                    send({"id": request_id, **payload})
                elif kind == "result":
                    return response
                elif kind == "error":
                    raise CompilationError(
                        response["message"],
                        diagnostics=[
                            Diagnostic._from_wire(item)
                            for item in response.get("diagnostics", [])
                        ],
                    )
                else:
                    raise BridgeError(f"Unknown Deno bridge response: {kind!r}")
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.terminate()
            raise BridgeError(f"Deno bridge communication failed: {error}") from error
        except BridgeError:
            self.terminate()
            raise
        except (KeyboardInterrupt, SystemExit):
            self.terminate()
            raise

    def terminate(self) -> None:
        self._terminated = True
        if self._process is not None and self._process.poll() is None:
            self._process.kill()

    def close(self) -> None:
        self._terminated = True
        if self._process is not None:
            process = self._process
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if process.stdout is not None:
                process.stdout.close()
        self._stderr.close()
