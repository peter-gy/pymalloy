"""Compiler process ownership at the Python tooling boundary."""

from concurrent.futures import ThreadPoolExecutor

import pytest

import pymalloy as pm
from pymalloy.errors import CompilerError


def test_tooling_reuses_one_process_across_concurrent_calls_and_replaces_failures(
    children,
):
    sources = [
        f"source: value_{i} is duckdb.sql('SELECT {i} AS value')" for i in range(4)
    ]
    with ThreadPoolExecutor(max_workers=4) as threads:
        formatted = list(threads.map(pm.format, sources))
    count = len(children)
    assert count <= 1
    for index, text in enumerate(formatted):
        parsed = pm.parse(text)
        assert parsed.symbols[0].name == f"value_{index}"
    assert len(children) == count
    if children:
        children[-1].kill()
        children[-1].wait(timeout=5)
        assert pm.format(sources[0]) == formatted[0]
        assert len(children) == count + 1


@pytest.mark.parametrize(
    "failure",
    [
        CompilerError("Compiler process stopped"),
        TimeoutError("Expired"),
    ],
)
def test_validation_propagates_infrastructure_failures(monkeypatch, failure):

    def compile(*args, **kwargs):
        raise failure

    monkeypatch.setattr(pm.Connection, "_model", compile)
    with pytest.raises(type(failure)) as caught:
        pm.connect().validate(pm.draft())
    assert caught.value is failure
