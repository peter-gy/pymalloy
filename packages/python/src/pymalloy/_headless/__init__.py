"""Load optional runtime dependencies at their execution boundary."""


def load_api():
    try:
        from . import api
    except ModuleNotFoundError as error:
        if error.name != "duckdb":
            raise
        raise ImportError("Headless execution requires pymalloy[headless]") from error
    return api
