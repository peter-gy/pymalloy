"""Author, validate, and bundle Malloy models from notebook agents.

Read the workflow shipped with this installed version::

    import pymalloy.agent as agent

    skill = agent.agent_skill()
    print(skill.body)
    print(skill.file("references/modeling.md").read_text())

Use references/api.md for immutable Python composition and scoped source edits,
references/artifacts.md for captured inputs and bundle replay, and
references/triage.md for compiler and execution failures.

Malloy owns language semantics. Draft.check() runs compiler checks and accepts
optional documentation lint policies. Draft.validate() executes supplied counterexample queries against
the configured data. Keep analytical intent and review in the producing project.

Syntax construction, widgets, and agent discovery use the base package. Parsing existing
Malloy and runtime checks need pymalloy[headless]. Browser widgets need no Deno.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import agent_plugins

__all__ = ["agent_plugin", "agent_skill"]


def agent_plugin() -> agent_plugins.Plugin:
    """Locate the Agent Plugin shipped with this installed PyMalloy version."""
    from pathlib import Path

    import agent_plugins

    return agent_plugins.Plugin(Path(__file__).parent / "_assets" / "agent")


def agent_skill() -> agent_plugins.Skill:
    """Return the model-authoring workflow and its selected reference files."""
    return agent_plugin().skill("pymalloy")
