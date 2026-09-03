from agent_core.domain.tool_profiles import ToolProfile, tool_names_for_profile


def test_research_profile_can_publish_governed_user_deliverables() -> None:
    tools = tool_names_for_profile(ToolProfile.RESEARCH)

    assert "files.publish" in tools
    assert {"command.run", "patch.apply", "git.status", "agent.research"}.isdisjoint(tools)
