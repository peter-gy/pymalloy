"""Measure dataframe snapshots, Parquet materialization, and source bundle scaling."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from importlib.metadata import version
from pathlib import Path

import polars as pl
import pyarrow as pa

import pymalloy as pm
from pymalloy.export import bundle


def benchmark(rows: int, samples: int) -> dict:
    frame = pl.DataFrame({"id": pl.arange(0, rows, eager=True)})
    frame = frame.with_columns(
        category=pl.col("id") % 20,
        amount=pl.col("id") * 0.125,
        label=(pl.col("id") % 100).cast(pl.String),
        nested=pl.struct(pl.col("id").alias("value")),
    )
    contiguous = frame.to_arrow()
    fragmented = pa.Table.from_batches(
        contiguous.to_batches(max_chunksize=max(1, rows // 64))
    )
    timings: dict[str, list[float]] = {}

    def measure(name, operation):
        started = time.perf_counter()
        result = operation()
        timings.setdefault(name, []).append(time.perf_counter() - started)
        return result

    # Warm imports/codecs separately from the measured data sizes.
    pm.data(frame.head(1)).inputs[0].materialize()
    with tempfile.TemporaryDirectory(prefix="pymalloy-input-benchmark-") as directory:
        root = Path(directory)
        for index in range(samples):
            for label, data in (("contiguous", contiguous), ("fragmented", fragmented)):
                source = measure(f"snapshot_{label}", lambda data=data: pm.data(data))
                measure(f"parquet_{label}", source.inputs[0].materialize)
            for count in (100, 1000, 5000):
                lines = [
                    f"source: s_{i} is duckdb.table('rows.csv')" for i in range(count)
                ]
                source = pm.ModelSource(
                    "memory://benchmark/model.malloy", "\n".join(lines)
                )
                data = root / "rows.csv"
                data.write_text("value\n42\n")
                measure(
                    f"bundle_{count}_tables",
                    lambda count=count, source=source, index=index, data=data: bundle(
                        source,
                        root / f"bundle-{count}-{index}",
                        files={"rows.csv": data},
                        format=False,
                    ),
                )
    return {
        "rows": rows,
        "samples": samples,
        "arrow_bytes": contiguous.nbytes,
        "versions": {
            name: version(name) for name in ("pymalloy", "pyarrow", "polars", "deno")
        },
        "notes": "Warm codecs. Snapshot captures immutable data; parquet includes write/readback verification/hash. Bundle includes native compiler startup, source rewriting, Python grammar generation, and filesystem publication.",
        "seconds": {
            name: {"median": statistics.median(values), "samples": values}
            for name, values in timings.items()
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.rows < 1 or args.samples < 1:
        parser.error("rows and samples must be positive")
    report = benchmark(args.rows, args.samples)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {name: result["median"] for name, result in report["seconds"].items()},
            indent=2,
        )
    )
