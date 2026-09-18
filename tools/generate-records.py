"""Generate the Python protocol records from the TypeScript protocol."""

from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
schema = root / "packages/python/schema/protocol.json"
with schema.open("w") as output:
    subprocess.run(
        [
            "pnpm",
            "exec",
            "ts-json-schema-generator",
            "--path",
            "packages/protocol/src/records.ts",
            "--type",
            "Records",
            "--tsconfig",
            "packages/python/schema/tsconfig.json",
            "--no-type-check",
        ],
        cwd=root,
        stdout=output,
        check=True,
    )
subprocess.run(["pnpm", "exec", "vp", "fmt", str(schema)], cwd=root, check=True)
subprocess.run(
    [
        sys.executable,
        "-m",
        "datamodel_code_generator",
        "--input",
        str(schema),
        "--output",
        str(root / "packages/python/src/pymalloy/_records.py"),
        "--input-file-type",
        "jsonschema",
        "--output-model-type",
        "msgspec.Struct",
        "--snake-case-field",
        "--enum-field-as-literal",
        "all",
        "--disable-timestamp",
        "--use-standard-collections",
        "--target-python-version",
        "3.12",
        "--use-generic-container-types",
        "--formatters",
        "ruff-check",
        "ruff-format",
        "--base-class",
        "pymalloy._record_base.Record",
        "--extra-fields",
        "forbid",
    ],
    cwd=root,
    check=True,
)
