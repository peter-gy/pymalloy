from pathlib import Path

import duckdb
import polars as pl
import pyarrow as pa

import pymalloy as pm
from pymalloy.result import Column


def test_materialized_result_survives_data_updates_and_model_close():
    with duckdb.connect() as connection:
        connection.execute("CREATE TYPE mood AS ENUM ('happy', 'sad')")
        connection.execute(
            "CREATE TABLE moods AS SELECT 'happy'::mood AS mood, "
            "[{'value': 9007199254740993::BIGINT}] AS items"
        )
        with pm.connect(database=connection).model(
            "run: duckdb.table('moods') -> {select: mood, items}"
        ) as model:
            result = model.query().run()
            connection.execute(
                "UPDATE moods SET mood = 'sad', items = [{'value': 9007199254740994::BIGINT}]"
            )
            updated = model.query().run()

    assert result.columns == (
        Column(name="mood", type="ENUM('happy', 'sad')"),
        Column(name="items", type='STRUCT("value" BIGINT)[]'),
    )
    assert pa.types.is_dictionary(result.to_arrow().schema.field("mood").type)
    expected = [{"mood": "happy", "items": [{"value": 9007199254740993}]}]
    assert result.to_arrow().to_pylist() == result.to_pylist() == expected
    assert result.to_polars().to_dicts() == expected
    assert pl.DataFrame(result).to_dicts() == pa.table(result).to_pylist() == expected
    assert updated.to_polars().to_dicts() == [
        {"mood": "sad", "items": [{"value": 9007199254740994}]}
    ]
    rows = result.to_pylist()
    rows[0]["items"][0]["value"] = 0
    assert result.to_pylist() == expected


def test_empty_select_and_copy_have_distinct_result_schemas(tmp_path: Path):
    empty = (
        pm.connect()
        .model("run: duckdb.sql('SELECT 1::BIGINT AS id WHERE FALSE') -> {select: id}")
        .query()
        .run()
    )
    source = tmp_path / "copy.malloysql"
    source.write_text(
        f">>>sql connection:duckdb\nCOPY (SELECT 42 AS id) TO '{tmp_path / 'data.parquet'}'"
    )
    with pm.connect() as connection:
        copied = connection.model(source).query().run()
    assert empty.columns == (Column(name="id", type="BIGINT"),)
    assert empty.to_arrow().schema == pa.schema([pa.field("id", pa.int64())])
    assert empty.to_pylist() == []
    assert empty.to_polars().schema == {"id": pl.Int64}
    assert empty.to_polars().shape == (0, 1)
    assert copied.columns == ()
    assert copied.to_arrow().schema == pa.schema([])
    assert copied.to_pylist() == []
    assert copied.to_polars().shape == (0, 0)
    with duckdb.connect() as connection:
        assert connection.execute(
            "SELECT * FROM read_parquet(?)", [str(tmp_path / "data.parquet")]
        ).fetchall() == [(42,)]
