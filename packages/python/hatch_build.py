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
            "headless.mjs",
            "widget/widget.LICENSE.txt",
            "headless.LICENSE.txt",
            "agent/plugin.json",
            "agent/skills/pymalloy/SKILL.md",
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
                "Missing built PyMalloy assets: "
                + ", ".join(missing)
                + ". Build JavaScript assets with pnpm build before packaging Python."
            )
