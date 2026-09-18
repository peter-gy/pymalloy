import json
import subprocess
import sys
from pathlib import Path

import pytest
from check_samples import (
    digest,
    execute_jupyter,
    execute_marimo,
    summarize_result,
    worker,
)


def test_result_comparison_preserves_order_unless_unordered_is_requested():
    rows = [(1, ["a", "b"]), (2, ["c"])]
    assert digest(rows) != digest(list(reversed(rows)))
    assert digest(rows, unordered=True) == digest(list(reversed(rows)), unordered=True)
    assert digest(rows) != digest([(1, ["b", "a"]), (2, ["c"])])
    assert digest(rows, unordered=True) != digest(
        [(1, ["b", "a"]), (2, ["c"])], unordered=True
    )
    assert digest(rows, unordered=True) != digest([*rows, rows[0]], unordered=True)


def test_result_comparison_rounds_floats_only_with_explicit_precision():
    rows = [(1.0000000001,)]
    assert digest(rows) != digest([(1.0000000002,)])
    assert digest(rows, float_precision=9) == digest(
        [(1.0000000002,)], float_precision=9
    )


@pytest.mark.parametrize("format", ["marimo", "jupyter"])
def test_notebook_results_keep_query_identity_nested_values_and_empty_columns(
    tmp_path, format
):
    import polars as pl

    from pymalloy.exports import Document, Query, jupyter, marimo
    from pymalloy.exports._python import query_variables

    document = Document(
        title="Identity",
        cells=(
            Query("a.b", "SELECT [2, 1] AS values", kind="select"),
            Query("a_b", "SELECT [1, 2] AS values", kind="select"),
            Query("empty", "SELECT 1 AS value WHERE false", kind="select"),
        ),
        data_root=tmp_path,
    )
    renderer, execute, suffix = {
        "marimo": (marimo, execute_marimo, ".py"),
        "jupyter": (jupyter, execute_jupyter, ".ipynb"),
    }[format]
    target = tmp_path / f"identity{suffix}"
    target.write_text(renderer.render(document, output_path=target))
    variables = dict(
        zip(
            (query.name for query in document.queries),
            query_variables(document),
            strict=True,
        )
    )
    actual = execute(target, variables, {})
    assert actual == {
        "a.b": summarize_result(pl.DataFrame({"values": [[2, 1]]})),
        "a_b": summarize_result(pl.DataFrame({"values": [[1, 2]]})),
        "empty": summarize_result(pl.DataFrame(schema={"value": pl.Int32})),
    }


@pytest.mark.parametrize("format", ["marimo", "jupyter"])
def test_sample_checker_detects_wrong_generated_notebook_values(
    tmp_path, monkeypatch, format
):
    from pymalloy.exports import jupyter, marimo

    model = tmp_path / "answer.malloynb"
    model.write_text(">>>sql connection:duckdb\nSELECT 42 AS value\n")
    renderer = {"marimo": marimo, "jupyter": jupyter}[format]
    render = renderer.render

    def wrong_values(*args, **kwargs):
        source = render(*args, **kwargs)
        assert "42 AS value" in source
        return source.replace("42 AS value", "99 AS value")

    monkeypatch.setattr(renderer, "render", wrong_values)
    result = worker(model, tmp_path, tmp_path / "answer.py")
    assert result["status"] == "notebook_failed", result
    assert result["queries"][0]["error"] == f"{format}: Result values differ"


@pytest.mark.parametrize("runtime", [False, True])
def test_sample_checker_executes_copy_before_reading_its_output(tmp_path, runtime):
    samples = tmp_path / "samples"
    samples.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    (samples / "copy.malloynb").write_text(""">>>sql connection:duckdb
COPY (SELECT 42 AS value) TO 'answer.parquet' (FORMAT PARQUET)
>>>sql
SELECT * FROM 'answer.parquet'
""")
    output = tmp_path / "results"
    command = [
        sys.executable,
        str(Path(__file__).with_name("check_samples.py")),
        str(samples),
        "--data-root",
        str(data),
        "--output",
        str(output),
        "--execute-writes",
    ]
    if runtime:
        command.append("--runtime")
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=120, check=False
    )
    records = json.loads((output / "results.json").read_text())["results"]
    assert result.returncode == 0, records
    assert records[0]["status"] == "passed"
    assert set(records[0]["notebooks"]) == {"marimo", "jupyter"}
    assert [query["status"] for query in records[0]["queries"]] == ["passed", "passed"]
    for query in records[0]["queries"]:
        assert query["verified"] == [
            "reference",
            *(["runtime"] if runtime else []),
            "marimo",
            "jupyter",
        ]
    assert (data / "answer.parquet").is_file()
