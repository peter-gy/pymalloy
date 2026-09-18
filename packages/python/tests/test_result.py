from pathlib import Path

import duckdb
import pyarrow as pa

from pymalloy._server.engine import Engine
from pymalloy.result import Column


def test_materialized_result_survives_later_queries_and_engine_close():
    engine = Engine()
    engine.connection.execute("CREATE TYPE mood AS ENUM ('happy', 'sad')")
    result = engine.run(
        "SELECT 'happy'::mood AS mood, [{'value': 9007199254740993::BIGINT}] AS items"
    )
    engine.run("SELECT 0 AS unrelated")
    engine.close()

    assert result.columns == (
        Column("mood", "ENUM('happy', 'sad')"),
        Column("items", 'STRUCT("value" BIGINT)[]'),
    )
    assert pa.types.is_dictionary(result.arrow().schema.field("mood").type)
    expected = [{"mood": "happy", "items": [{"value": 9007199254740993}]}]
    assert result.arrow().to_pylist() == result.rows() == expected
    assert result.polars().to_dicts() == expected
    rows = result.rows()
    rows[0]["items"][0]["value"] = 0
    assert result.rows() == expected


def test_empty_select_and_copy_have_distinct_result_schemas(tmp_path: Path):
    with duckdb.connect() as connection:
        engine = Engine(connection=connection)
        empty = engine.run("SELECT 1::BIGINT AS id WHERE FALSE")
        copied = engine.run(f"COPY (SELECT 42 AS id) TO '{tmp_path / 'data.parquet'}'")
    assert empty.columns == (Column("id", "BIGINT"),)
    assert empty.arrow().schema == pa.schema([pa.field("id", pa.int64())])
    assert empty.rows() == []
    assert copied.columns == ()
    assert copied.arrow().schema == pa.schema([])
    assert copied.rows() == []
    assert copied.polars().shape == (0, 0)
    with duckdb.connect() as connection:
        assert connection.execute(
            "SELECT * FROM read_parquet(?)", [str(tmp_path / "data.parquet")]
        ).fetchall() == [(42,)]
