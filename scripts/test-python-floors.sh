#!/usr/bin/env bash
# Run the Python suite against the wheel's declared dependency lower bounds.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

uv build --package pymalloy --no-sources --wheel --out-dir "$work/native" "$root"

floors="$(uv run --isolated --frozen --only-group release python - "$root/packages/python/pyproject.toml" <<'PY'
import sys
import tomllib

from packaging.requirements import Requirement

project = tomllib.load(open(sys.argv[1], "rb"))["project"]
for value in project["dependencies"]:
    requirement = Requirement(value)
    if requirement.marker is not None and not requirement.marker.evaluate():
        continue
    floors = [item.version for item in requirement.specifier if item.operator == ">="]
    if len(floors) != 1:
        raise ValueError(f"A dependency must declare one lower bound: {value}")
    print(f"{requirement.name}=={floors[0]}")
PY
)"
echo "Declared floors:"
echo "$floors"

uv venv --quiet --python 3.12 "$work/venv"
# shellcheck disable=SC2086
uv pip install --quiet --python "$work/venv" \
	"$(echo "$work"/native/pymalloy-*-cp312-abi3-*.whl)" $floors \
	pytest pytest-timeout polars "marimo[recommended]" nbformat nbclient ipykernel

cd "$root"
PATH="$work/venv/bin:$PATH" "$work/venv/bin/python" -m pytest -q -p no:cacheprovider
