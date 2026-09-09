from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime import LocalToolGateway
from agent_tools.skills_catalog import SkillMetadata, SkillReadResult


class Catalog:
    route = "injected"
    guidance_origin = "CLOUD"

    def list(self, *, limit: int = 100):
        return ((SkillMetadata("sample", "description", "source"),)[:limit], 0, False)

    def read(self, name: str, *, file_path: str = "SKILL.md"):
        assert name == "sample"
        return SkillReadResult(
            SkillMetadata("sample", "description", "source"),
            file_path,
            "guidance",
            8,
        )


def _call(name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=datetime.now(UTC),
    )


def test_injected_catalog_uses_existing_typed_skill_tools(tmp_path) -> None:
    gateway = LocalToolGateway(  # type: ignore[arg-type]
        tmp_path, skill_catalog=Catalog(), skill_component_names=("sample",)
    )
    try:
        names = {tool.name for tool in gateway.model_tools}
        assert {"skills.list", "skills.read"} <= names
        listed = gateway.execute(_call("skills.list", {}))
        read = gateway.execute(_call("skills.read", {"name": "sample"}))
        assert listed.status is read.status is ToolCallStatus.EXECUTED
        assert listed.metadata["route"] == read.metadata["route"] == "injected"
        assert "[UNTRUSTED CLOUD SKILL GUIDANCE]" in read.output
    finally:
        gateway.close()


def test_catalog_and_roots_are_mutually_exclusive(tmp_path) -> None:
    with pytest.raises(ValueError, match="skill_roots or skill_catalog"):
        LocalToolGateway(tmp_path, skill_roots=(tmp_path,), skill_catalog=Catalog())  # type: ignore[arg-type]


def test_gateway_construction_does_not_read_injected_catalog(tmp_path) -> None:
    catalog = Catalog()
    catalog.list = lambda **kwargs: pytest.fail("construction must not authorize")  # type: ignore[method-assign]
    gateway = LocalToolGateway(  # type: ignore[arg-type]
        tmp_path, skill_catalog=catalog, skill_component_names=("frozen-skill-id",)
    )
    try:
        assert gateway.effective_skill_components == ("frozen-skill-id",)
    finally:
        gateway.close()
