import subprocess

import pytest


@pytest.fixture
def children(monkeypatch):
    processes = []
    launch = subprocess.Popen

    def capture(*args, **kwargs):
        process = launch(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", capture)
    yield processes
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
