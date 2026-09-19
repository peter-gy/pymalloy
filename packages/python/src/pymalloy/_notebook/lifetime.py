"""Bind implicit display widgets to a marimo cell's lifetime when present."""

import sys


def own_display(widget) -> None:
    marimo = sys.modules.get("marimo")
    if marimo is None or not marimo.running_in_notebook():
        return

    # marimo closes its comm on rerun, but ipywidgets also owns a Python-side
    # registry entry. Close the widget through the same cell lifecycle so its
    # captured inputs and borrowed model references are released too.
    from marimo._runtime.cell_lifecycle_item import CellLifecycleItem
    from marimo._runtime.context import get_context

    class DisplayLifetime(CellLifecycleItem):
        def create(self, context) -> None:
            pass

        def dispose(self, context, deletion) -> bool:
            widget.close()
            return True

    get_context().cell_lifecycle_registry.add(DisplayLifetime())
