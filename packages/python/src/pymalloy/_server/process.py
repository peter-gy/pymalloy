from __future__ import annotations

import queue
import struct
import subprocess
import sysconfig
import threading
import time
from collections import deque
from concurrent.futures import Future
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import IO, Any

import msgspec

from pymalloy._model.errors import CompilerError
from pymalloy._protocol.records import CompilerReady, Response

_MAX_FRAME = 64 * 1024 * 1024
_DECODER = msgspec.json.Decoder(Response)


def _read(stream: IO[bytes], length: int) -> bytearray:
    data = bytearray(length)
    view = memoryview(data)
    offset = 0
    while offset < length:
        chunk = stream.read(length - offset)
        if not chunk:
            raise EOFError("Compiler output ended unexpectedly")
        view[offset : offset + len(chunk)] = chunk
        offset += len(chunk)
    return data


def _receive(stream: IO[bytes]) -> Response:
    length = struct.unpack(">I", _read(stream, 4))[0]
    if not 0 < length <= _MAX_FRAME:
        raise ValueError("Invalid compiler frame length")
    return _DECODER.decode(_read(stream, length))


class Process:
    """Own one serialized compiler connection and bounded stderr capture."""

    def __init__(self, *, memory_mb: int, timeout: float) -> None:
        try:
            deno = distribution("deno")
        except PackageNotFoundError as error:
            raise ImportError("Server execution requires pymalloy[server]") from error
        executable = "deno" + (sysconfig.get_config_var("EXE") or "")
        binaries = [
            Path(str(deno.locate_file(file)))
            for file in deno.files or ()
            if file.name == executable and Path(str(deno.locate_file(file))).is_file()
        ]
        if len(binaries) != 1:
            raise FileNotFoundError(
                "Deno's installed distribution must contain one executable. Reinstall pymalloy[server]."
            )
        if type(memory_mb) is not int or memory_mb <= 0:
            raise ValueError("compiler_memory_mb must be a positive integer")
        script = Path(__file__).parents[1] / "_assets" / "server.mjs"
        if not script.is_file():
            raise FileNotFoundError(f"Packaged compiler server is missing: {script}")
        self._process = subprocess.Popen(
            [
                str(binaries[0]),
                "run",
                "--no-config",
                "--no-npm",
                "--no-lock",
                "--no-prompt",
                "--quiet",
                "--deny-import",
                f"--v8-flags=--max-heap-size={memory_mb}",
                str(script),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._closed = False
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._pending: queue.SimpleQueue[tuple[bytes, Future[Response]] | None] = (
            queue.SimpleQueue()
        )
        self._stderr: deque[bytes] = deque(maxlen=16)
        self._ready: Future[Response] = Future()
        self._last = self._ready
        self._reader = threading.Thread(target=self._serve, daemon=True)
        self._errors = threading.Thread(target=self._read_errors, daemon=True)
        self._errors.start()
        self._reader.start()
        try:
            self._ready.result(timeout)
        except TimeoutError as error:
            self.close()
            raise TimeoutError("Compiler startup exceeded its deadline") from error
        except BaseException:
            self.close()
            raise

    @property
    def closed(self) -> bool:
        return self._closed or self._process.poll() is not None

    def _read_errors(self) -> None:
        stream = self._process.stderr
        assert stream is not None
        while chunk := stream.read(4096):
            self._stderr.append(chunk)

    def _serve(self) -> None:
        source, target = self._process.stdout, self._process.stdin
        assert source is not None and target is not None
        future = self._ready
        try:
            ready = _receive(source)
            if not isinstance(ready, CompilerReady):
                raise TypeError("Invalid compiler startup response")
            future.set_result(ready)
            while (item := self._pending.get()) is not None:
                payload, future = item
                view = memoryview(payload)
                while view:
                    count = target.write(view)
                    if not count:
                        raise EOFError("Compiler input closed")
                    view = view[count:]
                future.set_result(_receive(source))
            target.close()
        except (OSError, EOFError, TypeError, ValueError, msgspec.DecodeError) as error:
            self._errors.join(timeout=0.1)
            detail = b"".join(self._stderr).decode(errors="replace").strip()
            failure = CompilerError(f"Compiler process stopped: {detail or error}")
            if not future.done():
                future.set_exception(failure)
            self.close()

    def call(self, request: dict[str, Any], deadline: float) -> Response:
        payload = msgspec.json.encode(request)
        if len(payload) > _MAX_FRAME:
            raise ValueError("Compiler request exceeds 64 MiB")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Compiler deadline exceeded")
        future: Future[Response] = Future()
        with self._lock:
            if self._closed:
                raise CompilerError("Compiler process is closed")
            self._last = future
            self._pending.put((struct.pack(">I", len(payload)) + payload, future))
        try:
            return future.result(remaining)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        with self._lock:
            stopping = self._closed
            self._closed = True
            idle = self._last.done() and threading.current_thread() is not self._reader
        if stopping:
            if threading.current_thread() not in (self._reader, self._errors):
                self._stopped.wait()
            return
        try:
            if not idle and self._process.poll() is None:
                self._process.kill()
            self._pending.put(None)
            try:
                # EOF lets Deno persist its code cache after a completed operation.
                self._process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            for thread in (self._reader, self._errors):
                if thread is not threading.current_thread():
                    thread.join()
            while not self._pending.empty():
                item = self._pending.get()
                if item is not None:
                    item[1].set_exception(CompilerError("Compiler process is closed"))
            for stream in (
                self._process.stdin,
                self._process.stdout,
                self._process.stderr,
            ):
                if stream is not None:
                    stream.close()
        finally:
            self._stopped.set()
