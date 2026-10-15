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
    .sources(
        orders=pm.data(prepared, name="orders")
        .primary_key("id")
        .measure(revenue=pm.col("amount").sum().doc("Booked amount in USD."))
        .doc("One retained order per id, with amount of at least 10 USD.")
    )
    .queries(
        by_region=pm.source("orders").pipe(
            pm.view()
            .group_by(pm.col("region"))
            .aggregate(pm.col("revenue"))
            .order_by(pm.col("region"))
        )
    )
)
with pm.connect() as con:
    accepted = con.validate(
        candidate,
        {
            "unique_id": pm.source("orders").pipe(
                pm.view().group_by("id").aggregate(n=pm.count()).having(pm.col("n") > 1)
            )
        },
    ).require_valid()

with TemporaryDirectory() as directory:
    artifact = bundle(accepted, Path(directory) / "sales", query="by_region")
    result = runpy.run_path(str(artifact.model.parent / "replay.py"))["result"]
    print(result.to_pylist())
