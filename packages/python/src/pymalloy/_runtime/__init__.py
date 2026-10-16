"""Native DuckDB execution and compiled model lifetimes."""

import sys

if sys.platform == "emscripten":
    raise ImportError(
        "pymalloy.connect() requires native Python. In Pyodide, use "
        "`from pymalloy import browser` and `async with browser.connect() as connection`."
    )
