"""Runtime assets for browser widgets."""

from dataclasses import dataclass
from urllib.parse import urlsplit

__all__ = ["Bundle", "Runtime"]


@dataclass(frozen=True)
class Bundle:
    """Locate one matching DuckDB WebAssembly module and browser worker.

    Parameters
    ----------
    module : str
        Absolute HTTP(S) URL of the WebAssembly binary.
    worker : str
        Absolute HTTP(S) URL of the matching JavaScript worker.

    Notes
    -----
    Assets must be reachable from the notebook browser and allowed by its
    CORS and worker policies. Construction validates URL shape, not availability.

    Examples
    --------
    >>> from pymalloy.browser import Bundle
    >>> bundle = Bundle("https://assets.example/duckdb.wasm",
    ...                 "https://assets.example/duckdb.worker.js")
    >>> bundle.module
    'https://assets.example/duckdb.wasm'
    """

    module: str
    worker: str

    def __post_init__(self) -> None:
        for value in (self.module, self.worker):
            if not isinstance(value, str):
                raise TypeError("Browser asset URLs must be strings")
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(
                    "Browser asset URLs must be absolute HTTP or HTTPS URLs"
                )


@dataclass(frozen=True)
class Runtime:
    """Choose immutable DuckDB assets for a widget's lifetime.

    Parameters
    ----------
    mvp : Bundle
        Baseline WebAssembly module and worker.
    eh : Bundle, optional
        Exception-handling bundle selected when supported by the browser.

    Examples
    --------
    >>> import pymalloy as pm
    >>> from pymalloy.browser import Bundle, Runtime
    >>> runtime = Runtime(Bundle("https://assets.example/duckdb.wasm",
    ...                          "https://assets.example/duckdb.worker.js"))
    >>> widget = pm.MalloyWidget(
    ...     "run: duckdb.sql('SELECT 42 AS n') -> {select: n}", runtime=runtime)
    >>> widget.runtime is runtime
    True
    >>> widget.close()
    """

    mvp: Bundle
    eh: Bundle | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mvp, Bundle) or (
            self.eh is not None and not isinstance(self.eh, Bundle)
        ):
            raise TypeError("Runtime bundles must be browser.Bundle values")

    def _bundles(self) -> dict[str, dict[str, str]]:
        return {
            name: {"mainModule": bundle.module, "mainWorker": bundle.worker}
            for name, bundle in (("mvp", self.mvp), ("eh", self.eh))
            if bundle is not None
        }
