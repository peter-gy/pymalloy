"""Author and validate Malloy models from notebook agents.

Start with the instructions shipped with this installed version::

    import pymalloy as pm
    import pymalloy.agent as agent

    skill = agent.agent_skill()
    print(skill.body)
    print(skill.file("references/modeling.md").read_text())

Compose sources with pm.table(...).extend(pm.measure(revenue=pm.col("amount").sum())),
and name them with pm.draft().define(orders=source). Use pm.read_model(...) to
load existing Malloy with editable named expressions. All edits return new values.
Draft.to_python() emits editable Python operations. Supported scalar expressions
render canonically while preserving their meaning and surrounding model syntax.
Use pm.col and pm.given for references, pm.lit for values, and operators for
arithmetic and predicates. Use &, |, and ~ rather than Python truth testing.

Draft.check() returns compiler diagnostics and documentation warnings.
Draft.validate() runs named source/query fragments that must return no counterexamples.
Validation.save() writes the captured revision. Query.preview() bounds returned
rows during exploration. Parsing and runtime checks need pymalloy[server]. Syntax
construction and agent instructions work with the base install.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import agent_plugins

__all__ = ["agent_plugin", "agent_skill"]


def agent_plugin() -> agent_plugins.Plugin:
    """Locate the Agent Plugin shipped with this installed PyMalloy version."""
    import agent_plugins

    return agent_plugins.locate("pymalloy")


def agent_skill() -> agent_plugins.Skill:
    """Return the model-authoring workflow and its selected reference files."""
    return agent_plugin().skill("pymalloy")
