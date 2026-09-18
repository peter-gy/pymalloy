"""Interrupt active DuckDB work until its owner settles an expired operation."""

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import duckdb


@contextmanager
def interrupt_at(
    connection: duckdb.DuckDBPyConnection,
    deadline: float | None,
    *,
    message: str,
) -> Iterator[None]:
    if deadline is None:
        yield
        return
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError(message)
    expired = threading.Event()
    completed = threading.Event()

    def interrupt() -> None:
        expired.set()
        # DuckDB discards an interrupt delivered between statements.
        while not completed.is_set():
            connection.interrupt()
            completed.wait(0.01)

    timer = threading.Timer(remaining, interrupt)
    timer.start()
    user_interrupt = False
    try:
        yield
    except (KeyboardInterrupt, SystemExit):
        user_interrupt = True
        raise
    finally:
        completed.set()
        timer.cancel()
        timer.join()
        if not user_interrupt and (expired.is_set() or time.monotonic() >= deadline):
            raise TimeoutError(message)
