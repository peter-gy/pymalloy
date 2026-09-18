"""Runtime assets for browser widgets."""

from dataclasses import dataclass
from urllib.parse import urlsplit

__all__ = ["Bundle", "Runtime"]


@dataclass(frozen=True)
class Bundle:
    """Absolute HTTP URLs for one DuckDB WebAssembly module and worker."""

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
    """DuckDB bundles used for a widget's lifetime.

    `mvp` supplies the baseline WebAssembly bundle. Optional `eh` supplies the
    exception-handling bundle selected when the browser supports it.
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
