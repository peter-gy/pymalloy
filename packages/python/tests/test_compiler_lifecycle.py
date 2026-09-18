"""Compiler process ownership at the Python tooling boundary."""

from concurrent.futures import ThreadPoolExecutor
from time import monotonic

import pytest

import pymalloy as pm
from pymalloy._errors import CompilerError, PyMalloyError
from pymalloy._records import SourceReady
from pymalloy._server import tooling


def test_tooling_reuses_one_process_across_concurrent_calls_and_replaces_failures(
    monkeypatch,
):
    import subprocess

    tooling._tooling.close()
    processes = []
    popen = subprocess.Popen

    def start(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", start)
    try:
        sources = [
            f"source: value_{i} is duckdb.sql('SELECT {i} AS value')" for i in range(8)
        ]
        with ThreadPoolExecutor(max_workers=4) as threads:
            formatted = list(threads.map(pm.format, sources))
        for index, text in enumerate(formatted):
            assert f"value_{index}" in text
            assert not pm.parse(text, url=f"file:///model_{index}.malloy").diagnostics
            checked = pm.check(text)
            assert checked.ok
            assert checked.model.sources[0].name == f"value_{index}"
        with pytest.raises(pm.CompilationError):
            pm.format("run: ->")
        assert pm.format(sources[0]) == formatted[0]
        assert len(processes) == 1

        with (
            pytest.raises(CompilerError, match="Compiler has no model"),
            tooling.compiler_lease(monotonic() + 30) as compiler,
        ):
            compiler.request(
                {"op": "source"},
                SourceReady,
                describe=lambda sql: [],
                deadline=monotonic() + 30,
            )
        assert processes[0].poll() is not None
        assert pm.format(sources[0]) == formatted[0]
        assert len(processes) == 2
        processes[-1].kill()
        processes[-1].wait(timeout=5)
        assert pm.format(sources[0]) == formatted[0]
        assert len(processes) == 3
    finally:
        tooling._tooling.close()
    assert all(process.poll() is not None for process in processes)


def test_waiting_for_tooling_has_a_deadline_without_disrupting_active_work():
    tooling._tooling.close()
    try:
        with tooling.compiler_lease(monotonic() + 30) as compiler:
            with ThreadPoolExecutor(max_workers=1) as threads:

                def waiting():
                    with tooling.compiler_lease(monotonic() + 0.02):
                        pytest.fail("An active compiler cannot be leased twice")

                with pytest.raises(TimeoutError, match="Waiting for the tooling"):
                    threads.submit(waiting).result(timeout=5)
            assert not compiler.parse(
                "run: missing", url="file:///model.malloy", deadline=monotonic() + 30
            ).diagnostics
    finally:
        tooling._tooling.close()


@pytest.mark.parametrize(
    "failure",
    [
        CompilerError("Compiler process stopped"),
        TimeoutError("Expired"),
        OSError("Unreadable"),
    ],
)
def test_validation_propagates_infrastructure_failures(monkeypatch, failure):

    def compile(*args, **kwargs):
        raise failure

    monkeypatch.setattr(pm.Draft, "compile", compile)
    with pytest.raises(type(failure)) as caught:
        pm.draft().validate()
    assert caught.value is failure
    if isinstance(failure, CompilerError):
        assert isinstance(caught.value, PyMalloyError)


def test_tooling_process_exits_when_idle_and_starts_again(monkeypatch):
    import subprocess

    tooling._tooling.close()
    processes = []
    popen = subprocess.Popen

    def start(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", start)
    monkeypatch.setattr(tooling, "_IDLE_SECONDS", 0.02)
    try:
        expected = pm.format("run: missing")
        processes[0].wait(timeout=5)
        assert pm.format("run: missing") == expected
        assert len(processes) == 2
    finally:
        tooling._tooling.close()
