"""Measure notebook inspection, widget readback and native preview serialization."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
import tracemalloc
from importlib.metadata import version
from pathlib import Path

import pyarrow as pa

import pymalloy as pm
from pymalloy._notebook.subject import describe
from pymalloy._protocol.codec import decode_state
from pymalloy._protocol.records import Input
from pymalloy.result import Column, Result


def benchmark(samples: int) -> dict:
    wide = pm.query(
        pm.aggregate(
            **{f"metric_{i}": pm.col("amount").sum() + pm.lit(i) for i in range(1000)}
        )
    )
    wire = {
        "revision": 1,
        "status": "ready",
        "queries": [],
        "diagnostics": [],
        "error": None,
        "inspection": None,
        "result": {
            "sql": "SELECT ...",
            "connection_name": "duckdb",
            "schema": {
                "fields": [
                    {
                        "kind": "dimension",
                        "name": f"field_{i}",
                        "type": {"kind": "number_type"},
                    }
                    for i in range(8)
                ]
            },
            "data": {
                "kind": "array_cell",
                "array_value": [
                    {
                        "kind": "record_cell",
                        "record_value": [
                            {"kind": "number_cell", "number_value": r * 8 + c}
                            for c in range(8)
                        ],
                    }
                    for r in range(5000)
                ],
            },
        },
    }
    result = Result(
        "SELECT payload",
        (Column(name="payload", type="VARCHAR"),),
        pa.table({"payload": ["x" * (1024 * 1024)] * 20}),
    )
    subject = describe(result)
    request = Input(
        revision=1, definition_revision=1, action="inspect", query=None, givens={}
    )
    widget = pm.MalloyWidget("run: example", auto_run=False)

    def display():
        view = wide._display_()
        view.close()

    def publish():
        widget.query = str(time.perf_counter_ns())
        wire["revision"] = widget._input["revision"]
        widget.set_state({"_state": wire})

    operations = {
        "inspect_1000_fields": lambda: describe(wide),
        "display_1000_fields": display,
        "decode_5000_rows": lambda: decode_state(wire),
        "publish_5000_rows": publish,
        "ipc_20mb": lambda: subject.perform(request),
    }
    measurements = {}
    try:
        for name, operation in operations.items():
            operation()
            timings = []
            for _ in range(samples):
                start = time.perf_counter()
                value = operation()
                timings.append(time.perf_counter() - start)
                del value
            tracemalloc.start()
            try:
                value = operation()
                _, peak = tracemalloc.get_traced_memory()
                del value
            finally:
                tracemalloc.stop()
            measurements[name] = {
                "median_seconds": statistics.median(timings),
                "samples_seconds": timings,
                "peak_python_bytes": peak,
            }
    finally:
        widget.close()
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": {
            name: version(name)
            for name in ("anywidget", "msgspec", "pyarrow", "traitlets")
        },
        "measurements": measurements,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(benchmark(args.samples), indent=2) + "\n")
