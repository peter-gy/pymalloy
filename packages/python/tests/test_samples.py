import json
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pytest
from _corpus import digest
from check_samples import (
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


@pytest.mark.parametrize("format", ["marimo", "jupyter"])
def test_notebook_results_keep_query_identity_nested_values_and_empty_columns(
    tmp_path, format
):
    import polars as pl

    from pymalloy.export import Document, QueryCell, jupyter, marimo
    from pymalloy.export._plan import query_variables

    data = tmp_path / "seed.csv"
    data.write_text("value\n42\n")
    setup_names = ("remote_files", "check_files", "connection_config", "value", "str")
    document = Document(
        title="Identity",
        cells=(
            QueryCell("a.b", "SELECT [2, 1] AS values", kind="select"),
            QueryCell("a_b", "SELECT [1, 2] AS values", kind="select"),
            QueryCell("empty", "SELECT 1 AS value WHERE false", kind="select"),
            *(
                QueryCell(name, "SELECT * FROM 'seed.csv'", kind="select")
                for name in setup_names
            ),
        ),
        data_root=tmp_path,
        files={"seed.csv": data},
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
        **{
            name: summarize_result(pl.DataFrame({"value": [42]}))
            for name in setup_names
        },
    }


@pytest.mark.parametrize("format", ["marimo", "jupyter"])
def test_sample_checker_detects_wrong_generated_notebook_values(
    tmp_path, monkeypatch, format
):
    from pymalloy.export import jupyter, marimo

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


def test_sample_checker_executes_copy_before_reading_its_output(tmp_path):
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
        "--runtime",
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=120, check=False
    )
    records = json.loads((output / "results.json").read_text())["results"]
    assert result.returncode == 0, records
    assert records[0]["status"] == "passed"
    assert set(records[0]["notebooks"]) == {"marimo", "jupyter"}
    assert [query["status"] for query in records[0]["queries"]] == ["passed", "passed"]
    for query in records[0]["queries"]:
        assert set(query["verified"]) == {"reference", "runtime", "marimo", "jupyter"}
    assert (data / "answer.parquet").is_file()
    for filename in records[0]["queries"][0]["runtime_outputs"]:
        assert not Path(filename).exists()


@pytest.mark.parametrize(
    ("clause", "before", "after"),
    [
        ("select: amount order_by: amount asc", " asc", " desc"),
        ("where: amount > 10 select: amount", "10", "20"),
    ],
)
def test_roundtrip_checker_rejects_changed_sql_even_when_rows_match(
    tmp_path, monkeypatch, clause, before, after
):
    import check_roundtrip

    source = tmp_path / "model.malloy"
    source.write_text(
        "source: data is duckdb.sql('SELECT * FROM (VALUES (1),(2)) t(amount)')\n"
        f"query: result is data -> {{{clause}}}\n"
    )
    baseline = check_roundtrip.worker(source, tmp_path, tmp_path / "baseline")
    assert baseline["status"] == "passed", baseline
    reconstruct = check_roundtrip.reconstruct

    def changed_query(*args):
        text = reconstruct(*args)
        changed = text.replace(before, after)
        assert changed != text
        return changed

    monkeypatch.setattr(check_roundtrip, "reconstruct", changed_query)
    result = check_roundtrip.worker(
        source, tmp_path, tmp_path / "changed", unordered=True
    )
    assert result["status"] == "needs_review", result
    query = result["queries"][0]
    assert query["comparison"] == "multiset"
    assert query["status"] == "sql_mismatch"


def test_roundtrip_result_comparison_requires_explicit_order_and_precision_policy():
    from check_roundtrip import compare_values, result_summary

    from pymalloy.result import Column, Result

    original, reversed_summary, modified_summary = [
        result_summary(
            Result(
                "", (Column(name="value", type="DOUBLE"),), pa.table({"value": values})
            ),
            float_precision=9,
        )
        for values in [
            (1.0000000001, 2.0),
            (2.0, 1.0000000001),
            (1.0000000002, 2.0000000001),
        ]
    ]
    assert compare_values(original, reversed_summary) == "value_mismatch"
    assert compare_values(original, reversed_summary, unordered=True) == "multiset"
    assert compare_values(original, modified_summary) == "value_mismatch"
    assert (
        compare_values(original, modified_summary, float_precision=9)
        == "rounded_ordered"
    )


def test_notebook_scope_matches_python_bindings_with_comprehensions_and_closures(
    tmp_path,
):
    import importlib.util

    from pymalloy.export._scope import scope

    source = """value = 42
rows = [value for value in range(2)]
def read():
    local = value + increment
    return local
"""
    path = tmp_path / "cell.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location("cell", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    definitions, references = scope(source)
    assert definitions == {name for name in vars(module) if not name.startswith("_")}
    assert references == {"range", "increment"}
    module.increment = 5
    assert module.read() == 47
