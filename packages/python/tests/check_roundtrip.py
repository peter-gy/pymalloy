"""Check sample compilation and execution after symbolic Python reconstruction."""

import argparse
import hashlib
import json
import runpy
import sys
import time
from contextlib import ExitStack, closing
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit

from _corpus import checkout_revision, digest, run_worker, sample_paths


def normalize_sql(value):
    if isinstance(value, dict):
        return {
            key: normalize_sql(item)
            for key, item in value.items()
            if key
            not in {"query_location", "query_length", "stmt_location", "stmt_length"}
        }
    if isinstance(value, list):
        return [normalize_sql(item) for item in value]
    return value


def result_summary(result, *, float_precision=None):
    from pymalloy.analysis import to_dict

    rows = result.rows()
    summary = {
        "columns": to_dict(result.columns),
        "rows": len(rows),
        "ordered": digest(rows),
        "multiset": digest(rows, unordered=True),
    }
    if float_precision is not None:
        summary["rounded_ordered"] = digest(rows, float_precision=float_precision)
        summary["rounded_multiset"] = digest(
            rows, unordered=True, float_precision=float_precision
        )
    return summary


def compare_values(left, right, *, unordered=False, float_precision=None):
    if left["columns"] != right["columns"]:
        return "schema_mismatch"
    key = "multiset" if unordered else "ordered"
    if float_precision is not None:
        key = "rounded_" + key
    return key if left[key] == right[key] else "value_mismatch"


def reconstruct(text, url, output):
    import pymalloy as pm

    original = pm.read_model(text, url=url)
    if original.text != text:
        raise AssertionError("Reading changed source text")
    code = original.to_python()
    output.write_text(code)
    restored = runpy.run_path(str(output))["model"]
    if restored.names != original.names:
        raise AssertionError("Reconstruction changed declaration names")
    return restored.text


def worker(path, data_root, output, *, unordered=False, float_precision=None):
    import duckdb

    import pymalloy as pm

    policy = {"unordered": unordered, "float_precision": float_precision}
    output.mkdir(parents=True, exist_ok=True)
    record = {"status": "reconstruction_failed", "queries": []}
    try:
        with path.open(newline="") as handle:
            original_text = handle.read()
        text = original_text
        if path.suffix == ".malloy":
            text = reconstruct(text, path.as_uri(), output / "model.py")
            record["root_reconstructed"] = True
        else:
            record["root_reconstructed"] = False
        with ExitStack() as stack:
            connection = stack.enter_context(
                closing(duckdb.connect(config={"threads": "1", "memory_limit": "2GB"}))
            )
            connection.execute("SET file_search_path = ?", [str(data_root)])
            connection.execute("SET TimeZone='UTC'")
            record["status"] = "baseline_compile_failed"
            original = stack.enter_context(
                closing(pm.model(path, connection=connection, timeout=45))
            )
            snapshot = original.source()
            record["status"] = "reconstruction_failed"
            imports = {}
            for index, (url, source) in enumerate(snapshot.imports.items()):
                imports[url] = (
                    reconstruct(source, url, output / f"import-{index}.py")
                    if urlsplit(url).path.endswith(".malloy")
                    else source
                )
            record["imports_reconstructed"] = len(imports)
            record["status"] = "recompiled_failed"
            restored = stack.enter_context(
                closing(
                    pm.model(
                        pm.ModelSource(snapshot.url, text, imports),
                        connection=connection,
                        timeout=45,
                    )
                )
            )
            if [(query.name, query.kind) for query in original.queries] != [
                (query.name, query.kind) for query in restored.queries
            ]:
                raise AssertionError("Query identities changed")
            record["compiled"] = True
            record["status"] = "query_failed"
            for query in original.queries:
                item = {"name": query.name, "status": "failed"}
                record["queries"].append(item)
                left, right = original.query(query.name), restored.query(query.name)
                sql_left, sql_right = left.sql(), right.sql()
                item["sql_identical"] = sql_left == sql_right
                parsed = [
                    json.loads(
                        connection.execute(
                            "SELECT json_serialize_sql(?)", [sql]
                        ).fetchone()[0]
                    )
                    for sql in (sql_left, sql_right)
                ]
                item["sql_ast_equal"] = not any(
                    ast.get("error") for ast in parsed
                ) and normalize_sql(parsed[0]) == normalize_sql(parsed[1])
                item["sql_equivalent"] = item["sql_identical"] or item["sql_ast_equal"]
                # SQL notebook cells can write files. This checker executes only SELECT.
                if any(
                    statement.type != duckdb.StatementType.SELECT
                    for sql in (sql_left, sql_right)
                    for statement in connection.extract_statements(sql)
                ):
                    item["status"] = "write_not_executed"
                    continue
                item["original"] = result_summary(
                    left.run(timeout=45), float_precision=float_precision
                )
                item["restored"] = result_summary(
                    right.run(timeout=45), float_precision=float_precision
                )
                item["comparison"] = compare_values(
                    item["original"], item["restored"], **policy
                )
                if item["comparison"] in {"schema_mismatch", "value_mismatch"}:
                    item["baseline_repeat"] = result_summary(
                        left.run(timeout=45), float_precision=float_precision
                    )
                    item["baseline_comparison"] = compare_values(
                        item["original"], item["baseline_repeat"], **policy
                    )
                item["status"] = (
                    "sql_mismatch"
                    if not item["sql_equivalent"]
                    else "result_mismatch"
                    if item["comparison"] in {"schema_mismatch", "value_mismatch"}
                    else "passed"
                )
                if not item["sql_equivalent"]:
                    (
                        output / f"query-{len(record['queries'])}-original.sql"
                    ).write_text(sql_left)
                    (
                        output / f"query-{len(record['queries'])}-restored.sql"
                    ).write_text(sql_right)
            record["status"] = (
                "passed"
                if all(item["status"] == "passed" for item in record["queries"])
                else "needs_review"
            )
    except Exception as error:  # noqa: BLE001 - preserve corpus failures and continue
        record["error"] = f"{type(error).__name__}: {error}"
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--match", default="")
    parser.add_argument(
        "--unordered",
        action="store_true",
        help="compare top-level rows as multisets; nested order remains significant",
    )
    parser.add_argument(
        "--float-precision",
        type=int,
        choices=range(1, 18),
        metavar="1..17",
        help="round floats to this many significant digits (default: exact)",
    )
    args = parser.parse_args()
    root, data_root, output = (
        p.resolve() for p in (args.root, args.data_root, args.output)
    )
    if args.worker:
        print(
            json.dumps(
                worker(
                    args.worker,
                    data_root,
                    output,
                    unordered=args.unordered,
                    float_precision=args.float_precision,
                )
            )
        )
        return
    output.mkdir(parents=True, exist_ok=True)
    paths = sample_paths(root, args.match)
    if not paths:
        parser.error("No sample files matched")
    report = {
        "root": str(root),
        "data_root": str(data_root),
        "revision": checkout_revision(root),
        "versions": {name: version(name) for name in ("pymalloy", "duckdb", "deno")},
        "discovered": len(paths),
        "policy": {
            "threads": 1,
            "memory_limit": "2GB",
            "sql_equivalence": "identical SQL or identical normalized DuckDB syntax trees required",
            "row_order": "unordered" if args.unordered else "ordered",
            "float_precision": args.float_precision,
            "nested_order": "preserved",
            "notebook_root": "unchanged; captured Malloy imports reconstructed",
            "writes": "not executed",
        },
        "results": [],
    }
    for path in paths:
        relative = str(path.relative_to(root))
        target = output / "sources" / relative
        target.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            str(root),
            "--data-root",
            str(data_root),
            "--output",
            str(target),
            "--worker",
            str(path),
        ]
        if args.unordered:
            command.append("--unordered")
        if args.float_precision is not None:
            command.extend(["--float-precision", str(args.float_precision)])
        started = time.monotonic()
        record = run_worker(command, cwd=target, timeout=300)
        record.update(
            file=relative,
            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            seconds=round(time.monotonic() - started, 2),
        )
        report["results"].append(record)
        (output / "results.json").write_text(json.dumps(report, indent=2))
        print(relative, record["status"], len(record.get("queries", [])), flush=True)
    if any(record["status"] != "passed" for record in report["results"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
