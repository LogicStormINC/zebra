"""Orchestrator definition tests: ceiling, tool surface, no bypass."""

from __future__ import annotations

import pytest
from agent_orchestration.domain.orchestrator_definition import (
    ORCHESTRATOR_ALLOWED_CAPABILITIES,
    ORCHESTRATOR_DEFINITION_REF,
    ORCHESTRATOR_FORBIDDEN_CAPABILITIES,
    ORCHESTRATOR_TEAM_TOOLS_LOCKED,
    ORCHESTRATOR_TOOL_NAMES,
    ORCHESTRATOR_TOOLS,
    validate_orchestrator_definition,
)


class TestCeiling:
    def test_definition_ref_is_the_published_system_ref(self) -> None:
        assert ORCHESTRATOR_DEFINITION_REF == "system/orchestrator@1"

    def test_ceiling_has_exactly_eight_orchestration_capabilities(self) -> None:
        assert len(ORCHESTRATOR_ALLOWED_CAPABILITIES) == 8
        assert all(
            capability.startswith("orchestration.")
            for capability in ORCHESTRATOR_ALLOWED_CAPABILITIES
        )

    def test_forbidden_list_covers_the_plan_62_bypasses(self) -> None:
        expected = {
            "host.business.write",
            "connector.modify",
            "authority.issue",
            "agent_definition.publish",
            "worker.assign",
            "lease.override",
            "effect.force_retry",
            "workspace.force_merge",
        }
        assert ORCHESTRATOR_FORBIDDEN_CAPABILITIES == expected

    def test_validation_passes_and_returns_the_ceiling(self) -> None:
        assert validate_orchestrator_definition() == ORCHESTRATOR_ALLOWED_CAPABILITIES


class TestToolSurface:
    def test_exactly_the_eight_plan_63_tools(self) -> None:
        assert len(ORCHESTRATOR_TOOLS) == 8
        assert ORCHESTRATOR_TOOL_NAMES == {
            "orchestration.plan.submit",
            "orchestration.plan.inspect",
            "orchestration.task.spawn",
            "orchestration.task.list",
            "orchestration.task.wait",
            "orchestration.task.cancel",
            "orchestration.result.read",
            "orchestration.replan.submit",
        }

    def test_every_tool_scopes_inside_the_ceiling(self) -> None:
        for tool in ORCHESTRATOR_TOOLS:
            for scope in tool.scopes:
                assert scope in ORCHESTRATOR_ALLOWED_CAPABILITIES
                assert scope not in ORCHESTRATOR_FORBIDDEN_CAPABILITIES

    def test_team_tools_stay_locked(self) -> None:
        locked = set(ORCHESTRATOR_TEAM_TOOLS_LOCKED)
        assert not locked & ORCHESTRATOR_TOOL_NAMES
        assert len(locked) == 4


class TestTamperDetection:
    def test_validation_rejects_a_leaked_tool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agent_orchestration.domain import orchestrator_definition as module

        tampered = module.ORCHESTRATOR_TOOLS + (
            module.ORCHESTRATOR_TOOLS[0].__class__(
                name="host.business.write",
                description="bypass",
                scopes=("host.business.write",),
            ),
        )
        monkeypatch.setattr(module, "ORCHESTRATOR_TOOLS", tampered)
        with pytest.raises(module.OrchestratorDefinitionError):
            module.validate_orchestrator_definition()

    def test_validation_rejects_uncapped_tool_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agent_orchestration.domain import orchestrator_definition as module

        tool = module.ORCHESTRATOR_TOOLS[0]
        tampered = (
            tool.__class__(
                name=tool.name,
                description=tool.description,
                scopes=("host.business.write",),
                required_arguments=tool.required_arguments,
                argument_properties=tool.argument_properties,
            ),
        )
        monkeypatch.setattr(module, "ORCHESTRATOR_TOOLS", tampered)
        with pytest.raises(module.OrchestratorDefinitionError):
            module.validate_orchestrator_definition()
