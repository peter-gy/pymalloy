import json
import os
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest
from support import REPO, create_venv, pip_install

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(600)]

EXAMPLES = REPO / "examples"


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.headers: list[str] = []
        self.rows: list[list[str]] = []
        self._section = ""
        self._row: list[str] = []
        self._cell: list[str] = []
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"thead", "tbody"}:
            self._section = tag
        elif tag == "tr" and self._section:
            self._row = []
        elif tag in {"th", "td"} and self._section:
            self._in_cell = True
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self._in_cell:
            self._row.append("".join(self._cell).strip())
            self._in_cell = False
        elif tag == "tr" and self._section:
            if self._section == "thead" and self._row and not self.headers:
                self.headers = self._row
            elif self._section == "tbody" and self._row:
                self.rows.append(self._row)
            self._row = []
        elif tag in {"thead", "tbody"}:
            self._section = ""

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)


def _text(value: str | list[str]) -> str:
    return "".join(value) if isinstance(value, list) else value


def _rows(notebook: dict) -> tuple[str, list[dict[str, object]]]:
    plain_parts = []
    parsed: list[dict[str, object]] = []
    for cell in notebook["cells"]:
        if cell.get("cell_type") != "code":
            continue
        for output in cell.get("outputs", []):
            if output.get("output_type") != "execute_result":
                continue
            data = output.get("data", {})
            plain_parts.append(_text(data.get("text/plain", "")))
            html = _text(data.get("text/html", ""))
            if not html:
                continue
            parser = _TableParser()
            parser.feed(html)
            if "region" not in parser.headers:
                continue
            for row in parser.rows:
                record = dict(zip(parser.headers, row, strict=True))
                region = record["region"]
                if len(region) >= 2 and region[0] == region[-1] == '"':
                    region = region[1:-1]
                parsed.append(
                    {
                        "region": region,
                        "revenue": int(record["revenue"]),
                        "order_count": int(record["order_count"]),
                    }
                )
    return "\n".join(plain_parts), parsed


def _kernel(data: Path, name: str, python: Path) -> None:
    directory = data / "kernels" / name
    directory.mkdir(parents=True)
    (directory / "kernel.json").write_text(
        json.dumps(
            {
                "argv": [
                    str(python),
                    "-m",
                    "ipykernel_launcher",
                    "-f",
                    "{connection_file}",
                ],
                "display_name": name,
                "language": "python",
            }
        )
    )


@pytest.fixture(scope="session")
def notebook_kernels(tmp_path_factory: pytest.TempPathFactory, native_venv: Path):
    root = tmp_path_factory.mktemp("notebook-kernels")
    precompiled = create_venv(root / "precompiled")
    pip_install(precompiled, "duckdb", "polars", "ipykernel")
    pip_install(native_venv, "polars", "ipykernel")
    data = root / "jupyter"
    _kernel(data, "e2e-precompiled", precompiled / "bin" / "python")
    _kernel(data, "e2e-native", native_venv / "bin" / "python")
    return {"precompiled": precompiled, "native": native_venv, "data": data}


@pytest.mark.parametrize(
    ("profile", "kernel"),
    [("precompiled", "e2e-precompiled"), ("native", "e2e-native")],
)
def test_jupyter_nbconvert_executes_the_exported_notebook(
    tmp_path: Path, profile: str, kernel: str, notebook_kernels: dict
):
    if profile == "precompiled":
        probe = subprocess.run(
            [
                str(notebook_kernels["precompiled"] / "bin" / "python"),
                "-c",
                "import pymalloy",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert probe.returncode != 0
        assert "ModuleNotFoundError" in probe.stderr

    work = tmp_path / profile
    work.mkdir()
    shutil.copy(EXAMPLES / "orders.malloy", work / "orders.malloy")
    shutil.copy(EXAMPLES / "orders.csv", work / "orders.csv")
    notebook = work / "orders.ipynb"
    exported = subprocess.run(
        [
            "pymalloy",
            "export",
            str(work / "orders.malloy"),
            "--format",
            "jupyter",
            "--profile",
            profile,
            "--query",
            "orders.by_region",
            "-o",
            str(notebook),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert exported.returncode == 0, exported.stderr
    original = notebook.read_bytes()
    env = {**os.environ, "JUPYTER_PATH": str(notebook_kernels["data"])}
    executed = subprocess.run(
        [
            sys.executable,
            "-m",
            "jupyter",
            "nbconvert",
            "--execute",
            "--to",
            "notebook",
            "--output",
            "executed",
            f"--ExecutePreprocessor.kernel_name={kernel}",
            "--ExecutePreprocessor.timeout=90",
            notebook.name,
        ],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert executed.returncode == 0, executed.stderr
    assert notebook.read_bytes() == original
    plain, rows = _rows(json.loads((work / "executed.ipynb").read_text()))
    assert "North" in plain
    assert "105" in plain
    assert rows == [
        {"region": "North", "revenue": 105, "order_count": 3},
        {"region": "South", "revenue": 95, "order_count": 3},
    ]
