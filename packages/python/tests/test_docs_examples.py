"""Execute Python documentation examples against the built workspace."""

import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FENCE = re.compile(
    r"(?P<skip><!-- not-executed -->\n(?:[ \t]*\n)*)?^```python\n(?P<code>.*?)^```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)


@pytest.fixture(scope="module")
def example_directory(tmp_path_factory):
    directory = tmp_path_factory.mktemp("docs-examples")
    shutil.copytree(ROOT / "examples", directory / "examples")
    return directory


def test_python_documentation_examples(example_directory):
    pages = [
        ROOT / "README.md",
        ROOT / "packages/python/README.md",
        ROOT / "docs/index.md",
        *sorted((ROOT / "docs/guide").glob("*.md")),
        *sorted((ROOT / "docs/reference").glob("*.md")),
    ]
    examples = [
        (path.relative_to(ROOT), match.start(), match.group("code"))
        for path in pages
        for match in FENCE.finditer(path.read_text())
        if match.group("skip") is None
    ]

    assert examples

    def execute(example):
        path, offset, code = example
        line = (ROOT / path).read_text()[:offset].count("\n") + 1
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=example_directory,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, (
            f"{path}:{line}\n{result.stdout}\n{result.stderr}"
        )

    # Each fence gets a fresh interpreter. Bound concurrent interpreters.
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(execute, examples))
