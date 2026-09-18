"""Generate Python protocol records and identifier metadata from their owners."""

import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
subprocess.run(
    ["pnpm", "--filter", "@malloy-runtime/compiler", "lexicon"], cwd=root, check=True
)
subprocess.run(
    [
        sys.executable,
        "-m",
        "ruff",
        "format",
        str(root / "packages/python/src/pymalloy/_authoring/lexicon.py"),
    ],
    cwd=root,
    check=True,
)
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
        str(root / "packages/python/src/pymalloy/_protocol/records.py"),
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
        "pymalloy._protocol.base.Record",
        "--extra-fields",
        "forbid",
    ],
    cwd=root,
    check=True,
)
