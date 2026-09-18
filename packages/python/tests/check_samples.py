"""Compare native and exported notebook results for every sample in a checkout."""

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit

from _corpus import checkout_revision, digest, run_worker, sample_paths


def summarize_result(frame, *, unordered=False, float_precision=None):
    return {
        "columns": frame.columns,
        "rows": frame.height,
        "sha256": digest(
            frame.rows(), unordered=unordered, float_precision=float_precision
        ),
    }


def compare_results(expected, actual, *, sampled=False):
    if expected["columns"] != actual["columns"]:
        raise AssertionError("Result columns differ")
    if not sampled and expected != actual:
        raise AssertionError("Result values differ")


def execute_marimo(output, variables, policy):
    spec = importlib.util.spec_from_file_location("compiled_sample", output)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _, definitions = module.app.run()
    return {
        selector: summarize_result(definitions[variable], **policy)
        for selector, variable in variables.items()
    }


def execute_jupyter(output, variables, policy):
    import nbformat
    from nbclient import NotebookClient

    notebook = nbformat.read(output, as_version=4)
    nbformat.validate(notebook)
    notebook.cells.append(
        nbformat.v4.new_code_cell(
            "import sys as _sys\n"
            f"_sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n"
            "from check_samples import summarize_result as _summarize_result\n"
            "from IPython.display import JSON as _JSON, display as _display\n"
            f"_variables = {variables!r}\n"
            f"_policy = {policy!r}\n"
            "_display(_JSON({name: _summarize_result(globals()[variable], **_policy)\n"
            "    for name, variable in _variables.items()}))"
        )
    )
    executed = NotebookClient(
        notebook,
        timeout=45,
        kernel_name="python3",
        resources={"metadata": {"path": str(output.parent)}},
    ).execute()
    return next(
        output.data["application/json"]
        for output in executed.cells[-1].outputs
        if "application/json" in output.get("data", {})
    )


def worker(
    model: Path,
    data_root: Path,
    output: Path,
    execute_writes: bool = False,
    runtime: bool = False,
    *,
    unordered: bool = False,
    float_precision: int | None = None,
) -> dict:
    import re
    from contextlib import closing

    import duckdb
    import polars as pl

    import pymalloy as pm
    from pymalloy.export import compile, jupyter, marimo
    from pymalloy.export._python import query_variables

    policy = {"unordered": unordered, "float_precision": float_precision}
    record = {"status": "compile_failed", "queries": []}
    try:
        all_queries = model.suffix == ".malloy"
        book = compile(model, data_root=data_root, all=all_queries, timeout=45)
        second = compile(model, data_root=data_root, all=all_queries, timeout=45)
        notebooks = {
            "marimo": (marimo, output),
            "jupyter": (jupyter, output.with_suffix(".ipynb")),
        }
        record["notebooks"] = {}
        for name, (renderer, target) in notebooks.items():
            source = renderer.render(book, output_path=target)
            target.write_text(source)
            record["notebooks"][name] = str(target)
            if source != renderer.render(second, output_path=target):
                raise AssertionError(
                    f"Repeated {name} rendering changed notebook bytes"
                )
        record["deterministic"] = True
        if not execute_writes and any(query.kind == "copy" for query in book.queries):
            record["status"] = "write_not_executed"
            return record
        variables = {
            query.name: variable
            for query, variable in zip(book.queries, query_variables(book), strict=True)
            if query.kind == "select"
        }
        reference = {}
        sampled_queries = set()
        record["status"] = "reference_failed"
        with (
            duckdb.connect(
                config={"memory_limit": "1GB", "threads": "1"}
            ) as connection,
            closing(pm.model(model, data_root=data_root)) as loaded,
        ):
            connection.execute("SET VARIABLE data_root = ?", [str(data_root)])
            connection.execute("SET file_search_path = ?", [str(data_root)])
            connection.execute("SET TimeZone='UTC'")
            for query in book.queries:
                item = {"name": query.name, "status": "failed", "verified": []}
                record["queries"].append(item)
                raw = loaded.query(query.name).sql()
                if query.kind == "copy":
                    match = re.search(r"\bTO\s+'((?:[^']|'')*)'", raw, re.IGNORECASE)
                    if match is None or urlsplit(match[1]).scheme:
                        raise ValueError(
                            "COPY validation requires a literal local destination"
                        )
                    destinations = [(data_root / match[1].replace("''", "'")).resolve()]
                    for destination in destinations:
                        destination.relative_to(data_root)
                    raw = query.sql
                    item["outputs"] = [str(path) for path in destinations]
                    item["comparison"] = "write"
                else:
                    sampled = bool(
                        re.search(
                            r"\b(?:TABLESAMPLE|USING\s+SAMPLE)\b", raw, re.IGNORECASE
                        )
                    ) and not re.search(r"\bREPEATABLE\b", raw, re.IGNORECASE)
                    if sampled:
                        sampled_queries.add(query.name)
                    item["comparison"] = "schema_only_sampling" if sampled else "values"
                relation = connection.sql(raw)
                frame = (
                    pl.DataFrame(relation) if relation is not None else pl.DataFrame()
                )
                expected = summarize_result(frame, **policy)
                if query.kind == "select":
                    reference[query.name] = expected
                item.update(expected)
                item["verified"].append("reference")
                if runtime:
                    actual = summarize_result(
                        loaded.query(query.name).run().polars(), **policy
                    )
                    compare_results(
                        expected, actual, sampled=query.name in sampled_queries
                    )
                    item["verified"].append("runtime")
                item["status"] = "passed"
        record["status"] = "notebook_failed"
        for name, execute in [("marimo", execute_marimo), ("jupyter", execute_jupyter)]:
            # A prior execution's output would hide a missing or reordered COPY.
            for filename in {
                filename
                for item in record["queries"]
                for filename in item.get("outputs", [])
            }:
                Path(filename).unlink()
            actual = execute(notebooks[name][1], variables, policy)
            if actual.keys() != reference.keys():
                raise AssertionError(f"{name} result query identities differ")
            for item in record["queries"]:
                selector = item["name"]
                try:
                    if item["comparison"] != "write":
                        compare_results(
                            reference[selector],
                            actual[selector],
                            sampled=selector in sampled_queries,
                        )
                    for filename in item.get("outputs", []):
                        if not Path(filename).is_file():
                            raise AssertionError(f"COPY did not produce {filename}")
                    item["verified"].append(name)
                except AssertionError as error:
                    item["status"] = "failed"
                    item["error"] = f"{name}: {error}"
            if any(item["status"] == "failed" for item in record["queries"]):
                return record
        record["status"] = "passed"
    except Exception as error:  # noqa: BLE001 - record failures across compiler and notebook runtime boundaries
        record["error"] = str(error)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--match", default="")
    parser.add_argument(
        "--runtime", action="store_true", help="also compare public Model.run results"
    )
    parser.add_argument(
        "--execute-writes",
        action="store_true",
        help="execute COPY cells with destinations inside an isolated data root",
    )
    parser.add_argument(
        "--unordered",
        action="store_true",
        help="compare top-level rows as multisets (default: preserve row order)",
    )
    parser.add_argument(
        "--float-precision",
        type=int,
        choices=range(1, 18),
        metavar="1..17",
        help="round floats to this many significant digits (default: exact)",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    data_root = (args.data_root or root).resolve()
    if args.execute_writes and data_root == root:
        parser.error("--execute-writes requires an isolated --data-root")
    if args.worker:
        print(
            json.dumps(
                worker(
                    args.worker,
                    data_root,
                    args.output,
                    args.execute_writes,
                    args.runtime,
                    unordered=args.unordered,
                    float_precision=args.float_precision,
                )
            )
        )
        return
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    samples = sample_paths(root, args.match)
    metadata = {
        "root": str(root),
        "data_root": str(data_root),
        "revision": checkout_revision(root),
        "discovered": len(samples),
        "runtime": args.runtime,
        "versions": {
            name: version(name)
            for name in [
                "duckdb",
                "polars",
                "pyarrow",
                "marimo",
                "deno",
                "nbclient",
            ]
        },
        "comparison": {
            "row_order": "unordered" if args.unordered else "ordered",
            "float_precision": args.float_precision,
            "nested_order": "preserved",
            "unseeded_sampling": "columns_and_execution",
        },
    }
    records = []
    for model in samples:
        relative = str(model.relative_to(root))
        target = (
            output
            / "notebooks"
            / model.relative_to(root).with_suffix(model.suffix + ".py")
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        workdir = output / "work" / model.relative_to(root).with_suffix("")
        workdir.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            str(root),
            "--data-root",
            str(data_root),
            "--output",
            str(target),
            "--worker",
            str(model),
        ]
        for enabled, flag in [
            (args.execute_writes, "--execute-writes"),
            (args.runtime, "--runtime"),
            (args.unordered, "--unordered"),
        ]:
            if enabled:
                command.append(flag)
        if args.float_precision is not None:
            command.extend(["--float-precision", str(args.float_precision)])
        started = time.monotonic()
        record = run_worker(command, cwd=workdir, timeout=180)
        record.update(
            file=relative,
            source_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
            seconds=round(time.monotonic() - started, 2),
        )
        records.append(record)
        (output / "results.json").write_text(
            json.dumps({**metadata, "results": records}, indent=2)
        )
        print(relative, record["status"], len(record.get("queries", [])), flush=True)
    if not records:
        parser.error("No sample files matched")
    if any(record["status"] != "passed" for record in records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
