import json
import subprocess
import sys

import pytest

from pymalloy import browser


def test_browser_connection_names_its_required_python_runtime():
    with pytest.raises(ImportError, match="requires Python running in Pyodide"):
        browser.connect()


@pytest.mark.parametrize(
    "expression",
    [
        "pm.connect()",
        "pm.parse('run: missing')",
        "pm.format('run: missing')",
        "pm.read_model('source: values is duckdb.sql(\"SELECT 42 AS n\")')",
    ],
)
def test_native_entrypoints_direct_browser_python_to_async_connection(expression):
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            f"""
import json
import sys
sys.platform = 'emscripten'
import pymalloy as pm
try:
    {expression}
except ImportError as error:
    print(json.dumps({{'message': str(error), 'duckdb_imported': 'duckdb' in sys.modules}}))
else:
    raise AssertionError('Native entrypoint accepted browser Python')
""",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    observed = json.loads(completed.stdout)
    assert "browser.connect()" in observed["message"]
    assert observed["duckdb_imported"] is False
