from pathlib import Path

import pytest


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "e2e" in item.path.parts:
            item.add_marker(pytest.mark.e2e)
    markexpr = config.option.markexpr or ""
    if "e2e" in markexpr or any(
        "e2e" in Path(argument).parts for argument in config.args
    ):
        return
    selected = []
    deselected = []
    for item in items:
        if "e2e" in item.path.parts:
            deselected.append(item)
        else:
            selected.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected
