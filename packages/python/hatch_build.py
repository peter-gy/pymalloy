import hashlib
import json
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        assets = Path(self.root) / "src/pymalloy/_assets"
        required = (
            "widget/index.js",
            "widget/anywidget.json",
            "widget/widget.css",
            "agent/plugin.json",
            "agent/skills/pymalloy/SKILL.md",
            "pyodide/runtime.js",
            "pyodide/runtime.manifest.json",
        )
        manifest = assets / "widget/anywidget.json"
        if manifest.is_file():
            required += tuple(
                "widget/" + name for name in json.loads(manifest.read_text())["modules"]
            )
        missing = [
            name
            for name in required
            if not (assets / name).is_file() or not (assets / name).stat().st_size
        ]
        if missing:
            raise RuntimeError(
                "Missing built PyMalloy browser assets: "
                + ", ".join(missing)
                + ". Build JavaScript assets with pnpm build before packaging Python."
            )
        runtime = assets / "pyodide/runtime.js"
        metadata = json.loads((assets / "pyodide/runtime.manifest.json").read_text())
        with runtime.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if metadata["bundleSha256"] != digest:
            raise RuntimeError(
                "PyMalloy browser runtime digest differs. Run pnpm build."
            )
