from agent_core.domain.tool_profiles import ToolProfile, tool_names_for_profile


def test_research_profile_can_publish_governed_user_deliverables() -> None:
    tools = tool_names_for_profile(ToolProfile.RESEARCH)

    assert {"content.present", "files.publish"}.issubset(tools)
    assert {"command.run", "patch.apply", "git.status", "agent.research"}.isdisjoint(tools)


def test_research_coordinator_can_delegate_without_workspace_write_tools() -> None:
    tools = tool_names_for_profile(ToolProfile.RESEARCH_COORDINATOR)

    assert {"agent.research", "skills.list", "skills.read"}.issubset(tools)
    assert {"command.run", "patch.apply", "git.status", "tests.run"}.isdisjoint(tools)


def test_general_and_coding_profiles_can_present_governed_artifacts() -> None:
    assert "content.present" in tool_names_for_profile(ToolProfile.GENERAL)
    assert "content.present" in tool_names_for_profile(ToolProfile.CODING)
