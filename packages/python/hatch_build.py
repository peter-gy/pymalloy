from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        assets = Path(self.root) / "src/pymalloy/_assets"
        required = (
            "widget.js",
            "widget.css",
            "server.mjs",
            "widget.LICENSE.txt",
            "server.LICENSE.txt",
            "agent/plugin.json",
            "agent/skills/pymalloy/SKILL.md",
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
