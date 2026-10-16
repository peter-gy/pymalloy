"""Exercise an installed native wheel through Python's public API."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pyarrow as pa

import pymalloy as pm
import pymalloy._native
import pymalloy.agent


def main() -> None:
    wheel = Path(sys.argv[1])
    if sys.platform == "darwin":
        tag = re.search(r"macosx_(\d+)_(\d+)_", wheel.name)
        assert tag is not None and tuple(map(int, tag.groups())) >= (12, 0)
        binary = subprocess.check_output(
            ["otool", "-l", pymalloy._native.__file__], text=True
        )
        versions = re.findall(r"\bminos\s+(\d+)\.(\d+)", binary)
        assert versions and all(
            tuple(map(int, version)) >= (12, 0) for version in versions
        )

    text = "run: duckdb.sql('SELECT 42 AS amount') -> {select: amount}"
    assert pm.parse(text).ok
    assert pm.format(pm.format(text)) == pm.format(text)
    captured = pm.data(pa.table({"amount": [9007199254740993]}))
    draft = (
        pm.draft()
        .sources(numbers=captured)
        .queries(values=pm.source("numbers").pipe(pm.view().select(pm.col("amount"))))
    )
    with pm.connect() as connection:
        with connection.model(text) as model:
            assert model.query().run().to_pylist() == [{"amount": 42}]
        with connection.model(draft) as model:
            assert model.query("values").run().to_pylist() == [
                {"amount": 9007199254740993}
            ]
    widget = pm.MalloyWidget(text)
    assert widget.state["status"] == "idle"
    widget.close()
    assert pymalloy.agent.agent_skill().file("SKILL.md").is_file()
    print(
        f"Native wheel passed on Python {sys.version_info.major}.{sys.version_info.minor}"
    )


if __name__ == "__main__":
    main()
