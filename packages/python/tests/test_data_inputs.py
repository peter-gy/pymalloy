import base64
import gc
import hashlib
import json
import math
import runpy
from array import array
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from threading import Barrier

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import pymalloy as pm
from pymalloy.export import bundle


def totals(source):
    return (
        pm.draft()
        .define(orders=source)
        .queries(
            total=pm.ref("orders").pipe(
                pm.query(pm.aggregate(amount=pm.col("amount").sum()))
            )
        )
    )


def test_input_is_a_snapshot_and_materializes_once_across_composition_and_formatting():
    values = array("q", [12, 20])
    column = pa.Array.from_buffers(pa.int64(), 2, [None, pa.py_buffer(values)])
    captured = pm.data(pa.table({"amount": column}), name="orders")
    values[:] = array("q", [100, 100])
    draft = totals(
        captured.doc("Captured amounts.").extend(
            pm.dimension(double=pm.col("amount") * 2)
        )
    )
    formatted = draft.format()
    ready = Barrier(2, timeout=5)

    def materialize(candidate):
        ready.wait()
        return candidate.inputs[0].materialize()

    with ThreadPoolExecutor(max_workers=2) as pool:
        artifacts = list(pool.map(materialize, (draft, formatted)))
    assert len({artifact.path for artifact in artifacts}) == 1
    model = formatted.compile()
    try:
        assert model.run().rows() == [{"amount": 32}]
    finally:
        model.close()
    assert not draft.define(orders=pm.sql("SELECT 1 AS amount")).inputs


def test_accepted_inputs_export_after_model_close_and_relocate_without_python_data(
    tmp_path,
):
    frame = pl.DataFrame({"amount": [12, 20]})
    draft = totals(pm.data(frame, name="orders"))
    accepted = draft.validate().require_valid()
    materialized = accepted.draft.inputs[0].materialize()
    artifact = bundle(accepted, tmp_path / "export", query="total")
    manifest = json.loads(artifact.manifest.read_text())
    recorded = manifest["inputs"][0]
    expected_hash = hashlib.sha256(materialized.path.read_bytes()).hexdigest()
    assert recorded["sha256"] == expected_hash
    assert (
        hashlib.sha256(
            (artifact.model.parent / recorded["path"]).read_bytes()
        ).hexdigest()
        == expected_hash
    )
    assert recorded["rows"] == 2
    schema = pa.ipc.read_schema(
        pa.BufferReader(base64.b64decode(recorded["arrow_schema"]))
    )
    assert schema.equals(frame.to_arrow().schema, check_metadata=True)
    del draft, frame, accepted
    gc.collect()
    relocated = tmp_path / "relocated"
    artifact.model.parent.rename(relocated)
    result = runpy.run_path(str(relocated / "replay.py"))["result"]
    assert result.rows() == [{"amount": 32}]
    restored = runpy.run_path(str(relocated / "model.py"))["model"]
    model = restored.compile(data_root=relocated / "data")
    try:
        assert model.query("total").run().rows() == [{"amount": 32}]
    finally:
        model.close()


def test_native_values_survive_parquet_materialization():
    table = pa.table(
        {
            "id": pa.array([9007199254740993, None], type=pa.int64()),
            "money": pa.array([Decimal("12.30"), None], type=pa.decimal128(18, 2)),
            "nested": pa.array([[{"value": 1}, {"value": None}], None]),
            "when": pa.array(
                [datetime(2024, 1, 1, tzinfo=UTC), None],
                type=pa.timestamp("us", tz="Europe/Zurich"),
            ),
            "float": pa.array([float("nan"), -0.0]),
            "samples": pa.array([[float("nan"), -0.0, None], None]),
        }
    )
    source = pm.data(table)
    restored = pq.read_table(source.inputs[0].materialize().path)
    assert restored.schema.equals(table.schema, check_metadata=True)
    values = restored.to_pydict()
    floats = values.pop("float")
    samples = values.pop("samples")
    assert values == {
        "id": [9007199254740993, None],
        "money": [Decimal("12.30"), None],
        "nested": [[{"value": 1}, {"value": None}], None],
        "when": [datetime(2024, 1, 1, tzinfo=UTC), None],
    }
    assert samples[1] is None and samples[0][2] is None
    for numbers in (floats, samples[0]):
        assert math.isnan(numbers[0])
        assert numbers[1] == 0 and math.copysign(1, numbers[1]) == -1


def test_fragmented_dictionary_inputs_preserve_values_across_parquet_batches():
    first = pa.table({"label": pa.array(["a", "b"] * 17500).dictionary_encode()})
    last = pa.table({"label": pa.array(["b", "c"]).dictionary_encode()})
    table = pa.concat_tables([first, first, last])
    source = pm.data(table)
    artifact = source.inputs[0].materialize()
    restored = pq.read_table(artifact.path)
    assert restored.schema.equals(table.schema, check_metadata=True)
    assert restored.column("label").to_pylist() == ["a", "b"] * 35000 + ["b", "c"]


def test_lazy_and_lossy_inputs_require_explicit_conversion():
    with pytest.raises(TypeError, match="collect"):
        pm.data(pl.DataFrame({"amount": [1]}).lazy())
    with pytest.raises(TypeError, match="precision"):
        pm.data(pa.table({"when": pa.array([1], type=pa.timestamp("ns"))}))
    with pytest.raises(TypeError, match="precision"):
        pm.data(pa.table({"money": pa.array([Decimal(1)], type=pa.decimal256(50, 0))}))
    assert pm.data(
        pa.table({"when": pa.array([1000], type=pa.timestamp("ns"))})
    ).inputs[0].arrow().schema.field("when").type == pa.timestamp("us")


def test_python_reconstruction_preserves_explicit_shared_input_bindings(tmp_path):
    frame = pl.DataFrame({"amount": [12, 20]})
    captured = pm.data(frame, name="orders")
    draft = totals(captured).define(other=captured)
    with pytest.raises(ValueError, match="bindings"):
        draft.to_python()
    path = tmp_path / "model.py"
    path.write_text(draft.to_python(inputs={"orders": "frame"}))
    restored = runpy.run_path(str(path), init_globals={"frame": frame})["model"]
    assert len(restored.inputs) == 1
    model = restored.compile()
    try:
        assert model.run().rows() == [{"amount": 32}]
    finally:
        model.close()


def test_runtime_retains_temporary_input_owner_for_direct_queries():
    model = totals(pm.data(pl.DataFrame({"amount": [12, 20]}))).compile()
    gc.collect()
    try:
        assert model.run().rows() == [{"amount": 32}]
        direct = pm.data(pl.DataFrame({"amount": [7]})).pipe(
            pm.query(pm.aggregate(total=pm.col("amount").sum()))
        )
        query = model.query(direct)
        del direct
        gc.collect()
        assert query.run().rows() == [{"total": 7}]
    finally:
        model.close()


def test_arrow_capsule_and_record_batch_inputs():
    batch = pa.record_batch({"amount": [12, 20]})

    class Frame:
        def __arrow_c_stream__(self, requested_schema=None):
            return pa.Table.from_batches([batch]).__arrow_c_stream__(requested_schema)

    for value in [batch, Frame()]:
        assert pm.data(value).inputs[0].arrow().to_pydict() == {"amount": [12, 20]}


def test_managed_input_publication_rejects_source_only_saves_and_changed_inputs(
    tmp_path,
):
    draft = totals(pm.data(pl.DataFrame({"amount": [12, 20]}), name="orders"))
    with pytest.raises(ValueError, match="bundle"):
        draft.save(tmp_path / "incomplete.malloy")
    accepted = draft.validate(documentation=None).require_valid()
    destination = tmp_path / "bundle"
    with pytest.raises(ValueError, match="parameters differ"):
        bundle(accepted, destination, givens={"minimum": 7})
    assert not destination.exists()
    accepted.draft.inputs[0].materialize().path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed after materialization"):
        bundle(accepted, destination)
    assert not destination.exists()


def test_identical_assets_share_bytes_without_collapsing_capture_origins(tmp_path):
    frame = pl.DataFrame({"amount": [12, 20]})
    draft = totals(pm.data(frame, name="original")).define(
        copy=pm.data(frame, name="independent")
    )
    accepted = draft.validate(documentation=None).require_valid()
    artifact = bundle(accepted, tmp_path / "bundle", query="total")
    manifest = json.loads(artifact.manifest.read_text())
    assert len({item["id"] for item in manifest["inputs"]}) == 2
    assert len({item["path"] for item in manifest["inputs"]}) == 1
    assert len(list(artifact.data_root.rglob("*.parquet"))) == 1
