import importlib.metadata
import json
import subprocess
import sys


def test_capability_loads_the_installed_skill_and_references():
    capability = next(
        item
        for item in importlib.metadata.entry_points(group="marimo.agent.capability")
        if item.name == "pymalloy"
    )
    module = capability.load()
    plugin = module.agent_plugin()
    skill = module.agent_skill()
    assert plugin.manifest.name == "pymalloy"
    for name in [
        "SKILL.md",
        "references/modeling.md",
        "references/api.md",
        "references/artifacts.md",
        "references/triage.md",
    ]:
        assert skill.file(name).read_text(encoding="utf-8")


def test_authoring_and_agent_discovery_do_not_import_headless_or_notebook_dependencies():
    program = """
import importlib.abc, json, sys
class BlockServer(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'deno', 'duckdb', 'polars', 'pyarrow', 'marimo'}:
            raise AssertionError('Unexpected dependency: ' + fullname)
sys.meta_path.insert(0, BlockServer())
import pymalloy as pm
import pymalloy.agent as agent
candidate = pm.draft().define(
    values=pm.sql('SELECT 42 value').extend(
        pm.dimension(doubled=pm.col('value') * 2),
        pm.measure(total=pm.col('value').sum()),
    )
)
scope = {}
exec(candidate.to_python(), scope)
assert scope["model"]["values"]["doubled"].equals(pm.col('value') * 2)
print(json.dumps({'plugin': agent.agent_plugin().manifest.name, 'text': candidate.text}))
"""
    result = subprocess.run(
        [sys.executable, "-c", program], text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["plugin"] == "pymalloy"


def test_authoring_execution_identifies_the_missing_headless_extra():
    program = """
import importlib.abc, sys
class BaseInstall(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'deno', 'duckdb'}:
            raise ModuleNotFoundError(f'No module named {fullname!r}', name=fullname)
sys.meta_path.insert(0, BaseInstall())
import pymalloy as pm
from pymalloy.validation import Validation
candidate = pm.draft().define(values=pm.sql('SELECT 42 value'))
for operation in (candidate.compile, candidate.check, candidate.validate):
    try:
        operation()
    except ImportError as error:
        assert 'pymalloy[headless]' in str(error)
    else:
        raise AssertionError('Execution should require the headless extra')
"""
    result = subprocess.run(
        [sys.executable, "-c", program], text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_installed_workflow_recipes_execute_through_public_apis(tmp_path):
    from pymalloy import agent

    for name in ("artifacts", "triage"):
        text = agent.agent_skill().file(f"references/{name}.md").read_text()
        for index, block in enumerate(text.split("```python\n")[1:]):
            script = tmp_path / f"{name}-{index}.py"
            script.write_text(block.split("```", 1)[0])
            subprocess.run(
                [sys.executable, str(script)],
                check=True,
                cwd=tmp_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
