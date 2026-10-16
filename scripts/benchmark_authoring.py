"""Measure the native Python authoring loop. Run with --output timings.json."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from importlib.metadata import version
from pathlib import Path

import duckdb

import pymalloy as pm


def benchmark(samples: int) -> dict:
    timings: dict[str, list[float]] = {}

    def measure(name, operation):
        started = time.perf_counter()
        result = operation()
        timings.setdefault(name, []).append(time.perf_counter() - started)
        return result

    with tempfile.TemporaryDirectory(prefix="pymalloy-benchmark-") as directory:
        root = Path(directory)
        data = root / "orders.parquet"
        connection = duckdb.connect(config={"threads": "1"})
        try:
            connection.execute(
                "COPY (SELECT i AS id, i % 20 AS category, i * 0.125 AS amount "
                "FROM range(100000) t(i)) TO ? (FORMAT PARQUET)",
                [str(data)],
            )
            candidate = (
                pm.draft()
                .sources(
                    orders=pm.table(data)
                    .primary_key("id")
                    .measure(revenue=pm.col("amount").sum())
                )
                .queries(
                    totals=pm.source("orders").pipe(
                        pm.view()
                        .group_by(pm.col("category"))
                        .aggregate(pm.col("revenue"))
                        .order_by(pm.col("category"))
                    )
                )
            )
            source = root / "model.malloy"
            candidate.save(source)
            cold_command = [
                sys.executable,
                "-c",
                "import sys, pathlib, pymalloy as pm; pm.connect().model(pathlib.Path(sys.argv[1])).query().run()",
                str(source),
            ]
            model = pm.connect(database=connection).model(candidate)
            try:
                sql = model.query("totals").sql()
                for index in range(samples):
                    measure(
                        "cold_python_import_compile_execute",
                        lambda: subprocess.run(
                            cold_command, check=True, capture_output=True
                        ),
                    )
                    measure("parse_to_draft", lambda: pm.read_model(source))
                    measure("format_draft", candidate.format)
                    measure(
                        "check_draft",
                        lambda: pm.connect(database=connection).check(candidate),
                    )
                    measure(
                        "validate_draft",
                        lambda: pm.connect(database=connection).validate(
                            candidate,
                            {
                                "no_negative_revenue": pm.source("orders").pipe(
                                    pm.view()
                                    .aggregate(pm.col("revenue"))
                                    .having(pm.col("revenue") < 0)
                                )
                            },
                        ),
                    )
                    compiled = measure(
                        "compile_draft",
                        lambda: pm.connect(database=connection).model(candidate),
                    )
                    compiled.close()
                    edited = pm.source("orders").pipe(
                        pm.view()
                        .where(pm.col("category") >= index)
                        .aggregate(pm.col("revenue"))
                    )
                    measure(
                        "warm_adhoc_query_compile",
                        lambda edited=edited: model.query(
                            malloy="run: " + edited.text
                        ).sql(),
                    )
                    measure(
                        "schema_discovery_duckdb",
                        lambda: connection.execute(
                            "DESCRIBE SELECT * FROM read_parquet(?)", [str(data)]
                        ).fetchall(),
                    )
                    measure(
                        "execute_generated_sql_fetch",
                        lambda: connection.execute(sql).fetchall(),
                    )
                    measure("warm_named_query_sql", lambda: model.query("totals").sql())
                    result = measure(
                        "warm_named_query_run", lambda: model.query("totals").run()
                    )
                    measure("arrow_conversion", result.to_arrow)
                    measure("polars_conversion", result.to_polars)
                compiler = model.compiler_version
            finally:
                model.close()
        finally:
            connection.close()
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "versions": {
            name: version(name) for name in ("pymalloy", "duckdb", "pyarrow", "polars")
        },
        "compiler": compiler,
        "samples": samples,
        "input_rows": 100000,
        "notes": "Times include only the named boundary. Cold starts use fresh Python processes with an existing OS page cache. Schema timing isolates DuckDB DESCRIBE. Each result is newly materialized before conversion.",
        "seconds": {
            name: {"median": statistics.median(values), "samples": values}
            for name, values in timings.items()
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    report = benchmark(args.samples)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {name: value["median"] for name, value in report["seconds"].items()},
            indent=2,
        )
    )
