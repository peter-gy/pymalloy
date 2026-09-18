from __future__ import annotations

from typing import TYPE_CHECKING

from pymalloy._errors import CompilationError, ModelError
from pymalloy._source import ModelSource
from pymalloy.analysis import QueryDescriptor
from pymalloy.result import Result

if TYPE_CHECKING:
    from pymalloy._server.api import Model, Query, check, model, run
    from pymalloy._server.tooling import format, parse
    from pymalloy.widget import MalloyWidget

__all__ = [
    "CompilationError",
    "MalloyWidget",
    "Model",
    "ModelError",
    "ModelSource",
    "Query",
    "QueryDescriptor",
    "Result",
    "check",
    "format",
    "model",
    "parse",
    "run",
]


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


def __getattr__(name: str):
    if name == "MalloyWidget":
        from pymalloy.widget import MalloyWidget

        return MalloyWidget
    if name in {"model", "run", "check", "Model", "Query"}:
        try:
            from pymalloy._server import api
        except ModuleNotFoundError as error:
            if error.name != "duckdb":
                raise
            raise ImportError("Server execution requires pymalloy[server]") from error
        return getattr(api, name)
    if name in {"format", "parse"}:
        from pymalloy._server import tooling

        return getattr(tooling, name)
    raise AttributeError(name)
