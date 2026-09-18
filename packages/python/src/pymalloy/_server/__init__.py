"""Load optional runtime dependencies at their execution boundary."""


def load_api():
    try:
        from . import api
    except ModuleNotFoundError as error:
        if error.name != "duckdb":
            raise
        raise ImportError("Server execution requires pymalloy[server]") from error
    return api
