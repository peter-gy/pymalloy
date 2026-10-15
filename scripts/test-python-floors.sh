#!/usr/bin/env bash
# Run the Python suite against the built wheel with every runtime and headless
# dependency pinned to the lower bound declared in packages/python/pyproject.toml.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

uv build --package pymalloy --no-sources --wheel --out-dir "$work/dist" "$root"

floors="$(uv run --no-project python - "$root/packages/python/pyproject.toml" <<'PY'
import re
import sys
import tomllib

project = tomllib.load(open(sys.argv[1], "rb"))["project"]
for requirement in [*project["dependencies"], *project["optional-dependencies"]["headless"]]:
    name, floor = re.fullmatch(r"([A-Za-z0-9_.-]+)>=([^,]+)(?:,.*)?", requirement).groups()
    print(f"{name}=={floor}")
PY
)"
echo "Declared floors:"
echo "$floors"

uv venv --quiet --python 3.12 "$work/venv"
# shellcheck disable=SC2086
uv pip install --quiet --python "$work/venv" \
	"$(echo "$work"/dist/pymalloy-*.whl)[headless]" $floors \
	pytest pytest-timeout polars "marimo[recommended]" nbformat nbclient ipykernel

cd "$root"
PATH="$work/venv/bin:$PATH" "$work/venv/bin/python" -m pytest -q -p no:cacheprovider
