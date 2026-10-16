"""Compiler ownership at the Python tooling boundary."""

import os
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

import pymalloy as pm
from pymalloy.errors import CompilerError


def test_concurrent_tooling_calls_preserve_independent_source_results():
    sources = [
        f"source: value_{i} is duckdb.sql('SELECT {i} AS value')" for i in range(4)
    ]
    with ThreadPoolExecutor(max_workers=4) as threads:
        formatted = list(threads.map(pm.format, sources))
    for index, text in enumerate(formatted):
        parsed = pm.parse(text)
        assert parsed.symbols[0].name == f"value_{index}"
        assert pm.format(text) == text


def test_tooling_recovers_after_a_compiler_owner_closes():
    from pymalloy._compiler import tooling

    source = "source: numbers is duckdb.sql('SELECT 42 AS value')"
    formatted = pm.format(source)
    assert tooling._tooling._compiler is not None
    tooling._tooling._compiler.close()
    assert pm.format(source) == formatted
    assert pm.parse(formatted).symbols[0].name == "numbers"


def test_tooling_timer_start_failure_preserves_results_and_later_thread_calls(
    monkeypatch,
):
    import threading

    from pymalloy._compiler import tooling

    owner = tooling._ToolingCompiler()
    monkeypatch.setattr(tooling, "_tooling", owner)

    def fail_start(_timer):
        raise RuntimeError("can't start new thread")

    source = "source: numbers is duckdb.sql('SELECT 42 AS value')"
    try:
        with monkeypatch.context() as patch:
            patch.setattr(threading.Timer, "start", fail_start)
            assert pm.parse(source).symbols[0].name == "numbers"
        with ThreadPoolExecutor(max_workers=1) as threads:
            report = threads.submit(pm.parse, source).result(timeout=5)
        assert report.symbols[0].name == "numbers"
    finally:
        owner.close()


@pytest.mark.parametrize(
    "failure",
    [
        CompilerError("Compiler worker stopped"),
        TimeoutError("Expired"),
    ],
)
def test_validation_propagates_infrastructure_failures(monkeypatch, failure):
    def compile(*args, **kwargs):
        raise failure

    monkeypatch.setattr(pm.Connection, "_model", compile)
    with pm.connect() as connection, pytest.raises(type(failure)) as caught:
        connection.validate(pm.draft())
    assert caught.value is failure


@pytest.mark.skipif(not hasattr(os, "fork"), reason="POSIX fork is required")
@pytest.mark.parametrize("owner", ["tooling", "connection"])
def test_fork_rejects_inherited_busy_owners_before_locking(owner):
    program = r"""
import atexit
import gc
import os
import signal
import sys
import threading
import pymalloy as pm
from pymalloy._compiler import tooling
source = "run: duckdb.sql('SELECT 42 AS value') -> { select: value }"
assert pm.parse(source).ok
connection = pm.connect() if sys.argv[1] == "connection" else None
model = connection.model(source) if connection is not None else None
entered = threading.Event()
release = threading.Event()
lock = tooling._tooling._lock if sys.argv[1] == "tooling" else connection._lock

def hold():
    with lock:
        entered.set()
        assert release.wait(15)

thread = threading.Thread(target=hold)
thread.start()
assert entered.wait(5)
child = os.fork()
if child == 0:
    try:
        if sys.argv[1] == "tooling":
            operation = lambda: pm.parse(source)
            expected = pm.errors.CompilerError
        else:
            operation = lambda: model.query().run()
            expected = pm.errors.ClosedError
        try:
            operation()
        except expected as error:
            assert "fork" in str(error).lower(), str(error)
        else:
            raise AssertionError("Inherited owner accepted work")
        if model is not None:
            model.close()
            connection.close()
        tooling._tooling.close()
        del model, connection
        gc.collect()
        atexit._run_exitfuncs()
    except BaseException:
        import traceback
        traceback.print_exc()
        os._exit(1)
    if sys.argv[1] == "connection":
        # DuckDB native module finalization can deadlock after a threaded fork.
        # Python owners, finalizers and exit callbacks have already settled.
        os._exit(0)
    sys.exit(0)
watchdog = threading.Timer(10, lambda: os.kill(child, signal.SIGKILL))
watchdog.start()
try:
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 0, status
finally:
    watchdog.cancel()
    watchdog.join()
    release.set()
    thread.join(5)
if model is not None:
    assert model.query().run().to_pylist() == [{"value": 42}]
    model.close()
    connection.close()
assert pm.parse(source).ok
"""
    completed = subprocess.run(
        [sys.executable, "-c", program, owner],
        capture_output=True,
        text=True,
        check=False,
        timeout=25,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(
    not hasattr(signal, "setitimer"), reason="POSIX timers are required"
)
def test_tooling_signal_handler_reentry_fails_promptly():
    program = r"""
import signal
import pymalloy as pm
source = "\n".join(
    f"source: value_{i} is duckdb.sql('SELECT {i} AS value')"
    for i in range(2_000)
)
assert pm.parse("run: missing").ok
observed = []

def reenter(signum, frame):
    try:
        pm.parse("run: missing")
    except pm.errors.CompilerError as error:
        assert "reent" in str(error).lower(), str(error)
        observed.append(str(error))
    else:
        raise AssertionError("A signal handler reentered the active tooling owner")

signal.signal(signal.SIGALRM, reenter)
signal.setitimer(signal.ITIMER_REAL, 0.01)
try:
    formatted = pm.format(source)
finally:
    signal.setitimer(signal.ITIMER_REAL, 0)
assert observed
assert "value_1999" in formatted
assert pm.parse("run: missing").ok
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="POSIX signals are required")
@pytest.mark.parametrize("owner", ["tooling", "connection"])
@pytest.mark.parametrize("window", ["acquired", "releasing"])
def test_owners_reject_signal_reentry_during_lock_transitions(window, owner):
    program = r"""
import os
import signal
import sys
import time

import pymalloy as pm
from pymalloy._compiler import tooling

source = "source: numbers is duckdb.sql('SELECT 42 AS value')\nrun: numbers -> {select:value}"
assert pm.parse(source).ok
connection = pm.connect() if sys.argv[2] == "connection" else None
model = connection.model(source) if connection is not None else None
sibling = connection.model(source) if connection is not None else None
if connection is not None:
    assert model.query().run().to_pylist() == [{"value": 42}]
    assert sibling.query().run().to_pylist() == [{"value": 42}]
observed = []
lock = tooling._tooling._lock if connection is None else connection._lock

class SignalLock:
    armed = True

    def signal(self, window):
        if self.armed and sys.argv[1] == window:
            self.armed = False
            os.kill(os.getpid(), signal.SIGALRM)

    def acquire(self, *args, **kwargs):
        acquired = lock.acquire(*args, **kwargs)
        if acquired:
            self.signal("acquired")
        return acquired

    def release(self):
        self.signal("releasing")
        lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()

if connection is None:
    tooling._tooling._lock = SignalLock()
else:
    model._owner._lock = SignalLock()

def reenter(signum, frame):
    try:
        if connection is None:
            with tooling.compiler_lease(time.monotonic() + 0.06):
                raise AssertionError("Signal handler acquired the active compiler")
        else:
            sibling.query().run(timeout=0.06)
            raise AssertionError("Signal handler reentered the active connection")
    except BaseException as error:
        observed.append(error)

signal.signal(signal.SIGALRM, reenter)
try:
    if connection is None:
        assert pm.parse(source).symbols[0].name == "numbers"
    else:
        assert model.query().run().to_pylist() == [{"value": 42}]
    assert len(observed) == 1
    expected = pm.errors.CompilerError if connection is None else pm.errors.ClosedError
    assert isinstance(observed[0], expected), repr(observed[0])
    assert "reent" in str(observed[0]).lower(), str(observed[0])
    assert pm.format(source)
finally:
    if connection is not None:
        connection.close()
"""
    completed = subprocess.run(
        [sys.executable, "-c", program, window, owner],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(
    not hasattr(signal, "setitimer"), reason="POSIX timers are required"
)
def test_keyboard_interrupt_settles_active_compilation_and_preserves_siblings():
    program = r"""
import signal
import pymalloy as pm
source = "\n".join(
    f"source: value_{index} is duckdb.sql('SELECT {index} AS value')"
    for index in range(10_000)
) + "\nrun: value_0 -> { select: value }"
one = "run: duckdb.sql('SELECT 42 AS value') -> { select: value }"
with pm.connect() as connection:
    model = connection.model(one)
    sibling = connection.model(one)
    assert model.query().run().to_pylist() == [{"value": 42}]
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGALRM, interrupt)
    signal.setitimer(signal.ITIMER_REAL, 0.01)
    try:
        try:
            model.query(malloy=source).run()
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("Active compilation ignored the interrupt")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert model.closed
    assert sibling.query().run().to_pylist() == [{"value": 42}]
    assert connection.duckdb.execute("SELECT 42").fetchone() == (42,)
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


def test_native_job_timeout_settles_the_owner_and_preserves_siblings():
    import msgspec

    from pymalloy import _native
    from pymalloy._protocol.records import ParseRequest

    def request(source):
        return msgspec.json.encode(
            ParseRequest(
                source=source, url="memory://test/model.malloy", document_kind="model"
            )
        )

    compiler = _native.Compiler(memory_mb=256)
    sibling = _native.Compiler(memory_mb=256)
    try:
        warm = compiler.start(request("run: missing"))
        try:
            report = msgspec.json.decode(warm.step(None, timeout=10))["report"]
            assert report["diagnostics"] == []
        finally:
            warm.close()
        source = "\n".join(
            f"source: value_{index} is duckdb.sql('SELECT {index} AS value')"
            for index in range(10_000)
        )
        job = compiler.start(request(source))
        with pytest.raises(TimeoutError):
            job.step(None, timeout=0.01)
        assert compiler.closed
        job.close()
        job.close()
        healthy = sibling.start(request("source: numbers is duckdb.table('missing')"))
        try:
            report = msgspec.json.decode(healthy.step(None, timeout=10))["report"]
            assert report["symbols"][0]["name"] == "numbers"
        finally:
            healthy.close()
    finally:
        compiler.close()
        sibling.close()


def test_managed_heap_exhaustion_preserves_the_python_process_and_siblings():
    program = r"""
import duckdb
import pymalloy as pm
one = "run: duckdb.sql('SELECT 42 AS value') -> { select: value }"
with duckdb.connect() as native, pm.connect(native) as connection:
    sibling = connection.model(one)
    with pm.connect(native, compiler_memory_mb=16) as constrained:
        try:
            constrained.model(one)
        except pm.errors.CompilerError as error:
            assert "heap" in str(error).lower() or "memory" in str(error).lower(), str(error)
        else:
            raise AssertionError("Compilation exceeded its managed heap budget")
    assert sibling.query().run().to_pylist() == [{"value": 42}]
    assert native.execute("SELECT 42").fetchone() == (42,)
    with connection.model(one) as replacement:
        assert replacement.query().run().to_pylist() == [{"value": 42}]
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


def test_closing_a_job_waiting_for_source_answers_closes_its_compiler():
    import msgspec

    from pymalloy import _native
    from pymalloy._protocol.records import BeginRequest, Connection

    compiler = _native.Compiler(memory_mb=256)
    job = compiler.start(
        msgspec.json.encode(
            BeginRequest(
                source="import 'shared.malloy'\nrun: numbers -> { select: value }",
                url="memory://test/model.malloy",
                document_kind="model",
                connection=Connection(name="duckdb", dialect="duckdb"),
            )
        )
    )
    try:
        response = msgspec.json.decode(job.step(None, timeout=10))
        assert response["needs"]["urls"] == ["memory://test/shared.malloy"]
        job.close()
        job.close()
        assert compiler.closed
        with pytest.raises(RuntimeError, match="closed"):
            job.step(None, timeout=1)
    finally:
        compiler.close()
