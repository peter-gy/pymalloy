"""Capture Polars preparation as ordinary Malloy and Parquet, then replay."""

import runpy
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl

import pymalloy as pm
from pymalloy.export import bundle

orders = pl.DataFrame(
    {"id": [1, 2, 3], "region": ["North", "South", "North"], "amount": [12, 20, 8]}
)
prepared = orders.filter(pl.col("amount") >= 10)
candidate = (
    pm.draft()
    .define(
        orders=pm.data(prepared, name="orders")
        .extend(
            pm.primary_key("id"),
            pm.measure(revenue=pm.col("amount").sum().doc("Booked amount in USD.")),
        )
        .doc("One retained order per id, with amount of at least 10 USD.")
    )
    .queries(
        by_region=pm.ref("orders").pipe(
            pm.query(
                pm.group_by(pm.col("region")),
                pm.aggregate(pm.col("revenue")),
                pm.order_by(pm.col("region")),
            )
        )
    )
)
accepted = candidate.validate(
    {
        "unique_id": pm.ref("orders").pipe(
            pm.query(
                pm.group_by(pm.col("id")),
                pm.aggregate(n=pm.count()),
                pm.having(pm.col("n") > 1),
            )
        ),
    }
).require_valid()

with TemporaryDirectory() as directory:
    artifact = bundle(accepted, Path(directory) / "sales", query="by_region")
    result = runpy.run_path(str(artifact.model.parent / "replay.py"))["result"]
    print(result.rows())
