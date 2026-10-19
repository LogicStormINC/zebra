"""Skill bytes use their catalog authority; workspace tools still require runtime."""

import asyncio
from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime import LocalToolGateway, WorkspaceQuotaError
from agent_runtime.deferred import DeferredRuntime
from agent_tools.skills_catalog import LocalSkillCatalog


def call(tool_name, **arguments):
    return ToolCall(tool_call_id=new_tool_call_id(), name=tool_name, arguments=arguments,
                    created_at=datetime.now(UTC))


def test_skill_reads_skip_runtime_but_workspace_still_requires_quota(tmp_path):
    skill = tmp_path / "skills" / "sample"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: sample\ndescription: read-only\n---\nguide")
    (skill / "references" / "marker.txt").write_text("bounded reference")
    prepared = []

    def prepare():
        prepared.append(True)
        raise WorkspaceQuotaError("workspace must remain quota-qualified")

    deferred = DeferredRuntime(prepare)
    gateway = LocalToolGateway(tmp_path / "workspace", runtime=deferred,
        skill_catalog=LocalSkillCatalog((tmp_path / "skills",)),
        skill_component_names=("sample",))
    try:
        for tool in (call("skills.list"), call("skills.read", name="sample"),
                     call("skills.read", name="sample", file_path="references/marker.txt")):
            result = gateway.execute(tool)
            assert result.status is ToolCallStatus.EXECUTED
        assert "bounded reference" in result.output
        assert gateway.execute(call("skills.read", name="sample",
            file_path="../outside")).status is ToolCallStatus.FAILED
        assert prepared == []
        with pytest.raises(WorkspaceQuotaError, match="quota-qualified"):
            gateway.execute(call("files.list"))
        assert prepared == [True]
    finally:
        gateway.close()
        deferred.close()


@pytest.mark.parametrize("name", ["skills.list", "skills.read"])
def test_cancelled_skill_call_never_prepares_or_reads(tmp_path, name):
    def fail(*args, **kwargs):
        raise AssertionError("cancelled call must not prepare or read")

    class Catalog:
        list = read = fail

    def stopped():
        raise asyncio.CancelledError("Task stopped")

    deferred = DeferredRuntime(fail)
    gateway = LocalToolGateway(tmp_path, runtime=deferred, skill_catalog=Catalog(),
        skill_component_names=("sample",),
        network_cancellation_check=stopped)
    try:
        with pytest.raises(asyncio.CancelledError, match="Task stopped"):
            gateway.execute(call(name))
    finally:
        gateway.close()
        deferred.close()
