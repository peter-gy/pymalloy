import json
import sys
import textwrap
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from support import run_to_completion

import pymalloy as pm
from pymalloy.export import bundle

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(180)]

ROWS = '[{"revenue": "20"}]'
READER_ROWS = '[{"value": 42}]'


def _print_model(bundle_dir: Path) -> str:
    program = textwrap.dedent(
        """\
        import json
        import sys
        from pathlib import Path

        import pymalloy as pm

        bundle = Path(sys.argv[1])
        manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
        with pm.connect(
            data_root=bundle / manifest["data_root"],
            name=manifest["connection_name"],
        ) as connection:
            rows = (
                connection.model(bundle / manifest["model"])
                .query(manifest["query"])
                .run(givens=manifest["givens"])
                .to_pylist()
            )
        print(json.dumps(rows, ensure_ascii=False, default=str, allow_nan=False))
        """
    )
    completed = run_to_completion(
        [sys.executable, "-c", program, str(bundle_dir)],
        cwd=bundle_dir.parent / "model-cwd",
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def test_bundle_replay_runs_as_a_subprocess(tmp_path: Path):
    originals = tmp_path / "original"
    originals.mkdir()
    parquet = originals / "café orders.parquet"
    pq.write_table(pa.table({"id": [1, 2], "amount": [12, 20]}), parquet)
    model = originals / "orders.malloy"
    model.write_text(
        """##! experimental.givens
given: cutoff :: number is 0
source: orders is duckdb.sql("SELECT * FROM read_parquet('café orders.parquet')") extend {
  measure: revenue is amount.sum()
}
query: total is orders -> { where: amount > $cutoff aggregate: revenue }
query: duplicate_ids is orders -> {
  group_by: id
  aggregate: n is count()
  having: n > 1
}
""",
        encoding="utf-8",
    )
    draft = pm.read_model(model)
    with pm.connect(data_root=originals) as connection:
        report = connection.validate(
            draft,
            {"duplicate_ids": draft["duplicate_ids"]},
            givens={"cutoff": 15},
        )
    assert report.ok
    assert report.checks[0].status == "passed"
    written = bundle(
        report,
        tmp_path / "export",
        files={"café orders.parquet": parquet},
        query="total",
    )
    assert json.loads(written.manifest.read_text(encoding="utf-8"))["files"]
    parquet.unlink()
    relocated = tmp_path / "relocated"
    written.model.parent.rename(relocated)
    for name in ("replay-cwd", "model-cwd"):
        (tmp_path / name).mkdir()
    replay = run_to_completion(
        [sys.executable, str(relocated / "replay.py")],
        cwd=tmp_path / "replay-cwd",
        timeout=60,
    )
    assert replay.returncode == 0, replay.stderr
    assert replay.stdout.strip() == ROWS
    assert _print_model(relocated) == ROWS


def test_bundle_replay_refuses_a_shadowing_directory(tmp_path: Path):
    csv = tmp_path / "rows.csv"
    csv.write_text("value\n42\n")
    model = tmp_path / "reader.malloy"
    model.write_text(
        """run: duckdb.sql("SELECT * FROM read_csv('rows.csv')") -> {select: value}\n"""
    )
    artifact = bundle(
        pm.ModelSource(model.resolve().as_uri(), model.read_text()),
        tmp_path / "bundle",
        files={"rows.csv": csv},
    )
    csv.unlink()
    relocated = tmp_path / "relocated"
    artifact.model.parent.rename(relocated)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    replay = run_to_completion(
        [sys.executable, str(relocated / "replay.py")],
        cwd=elsewhere,
        timeout=60,
    )
    assert replay.returncode == 0, replay.stderr
    assert replay.stdout.strip() == READER_ROWS

    (elsewhere / "rows.csv").write_text("value\n99\n")
    shadowed = run_to_completion(
        [sys.executable, str(relocated / "replay.py")],
        cwd=elsewhere,
        timeout=60,
    )
    assert shadowed.returncode != 0
    assert "shadowed by the current directory" in shadowed.stderr
    assert "99" not in shadowed.stdout
