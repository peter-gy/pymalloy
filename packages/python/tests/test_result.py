from pathlib import Path

import duckdb
import polars as pl
import pyarrow as pa

import pymalloy as pm
from pymalloy._headless.engine import Engine
from pymalloy.result import Column


def test_materialized_result_survives_data_updates_and_model_close():
    with duckdb.connect() as connection:
        connection.execute("CREATE TYPE mood AS ENUM ('happy', 'sad')")
        connection.execute(
            "CREATE TABLE moods AS SELECT 'happy'::mood AS mood, "
            "[{'value': 9007199254740993::BIGINT}] AS items"
        )
        with pm.model(
            "run: duckdb.table('moods') -> {select: mood, items}",
            connection=connection,
        ) as model:
            result = model.run()
            connection.execute(
                "UPDATE moods SET mood = 'sad', items = [{'value': 9007199254740994::BIGINT}]"
            )
            updated = model.run()

    assert result.columns == (
        Column(name="mood", type="ENUM('happy', 'sad')"),
        Column(name="items", type='STRUCT("value" BIGINT)[]'),
    )
    assert pa.types.is_dictionary(result.arrow().schema.field("mood").type)
    expected = [{"mood": "happy", "items": [{"value": 9007199254740993}]}]
    assert result.arrow().to_pylist() == result.rows() == expected
    assert result.polars().to_dicts() == expected
    assert updated.polars().to_dicts() == [
        {"mood": "sad", "items": [{"value": 9007199254740994}]}
    ]
    rows = result.rows()
    rows[0]["items"][0]["value"] = 0
    assert result.rows() == expected


def test_empty_select_and_copy_have_distinct_result_schemas(tmp_path: Path):
    empty = pm.run(
        "run: duckdb.sql('SELECT 1::BIGINT AS id WHERE FALSE') -> {select: id}"
    )
    with duckdb.connect() as connection:
        engine = Engine(connection=connection)
        copied = engine.run(f"COPY (SELECT 42 AS id) TO '{tmp_path / 'data.parquet'}'")
    assert empty.columns == (Column(name="id", type="BIGINT"),)
    assert empty.arrow().schema == pa.schema([pa.field("id", pa.int64())])
    assert empty.rows() == []
    assert empty.polars().schema == {"id": pl.Int64}
    assert empty.polars().shape == (0, 1)
    assert copied.columns == ()
    assert copied.arrow().schema == pa.schema([])
    assert copied.rows() == []
    assert copied.polars().shape == (0, 0)
    with duckdb.connect() as connection:
        assert connection.execute(
            "SELECT * FROM read_parquet(?)", [str(tmp_path / "data.parquet")]
        ).fetchall() == [(42,)]
