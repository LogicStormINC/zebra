from enum import StrEnum


class ToolProfile(StrEnum):
    GENERAL = "general"
    CODING = "coding"
    RESEARCH = "research"


GENERAL_TOOL_NAMES = frozenset(
    {
        "agent.clarify",
        "agent.plan",
        "agent.research",
        "command.run",
        "files.list",
        "files.read",
        "files.publish",
        "files.search",
        "patch.apply",
        "sessions.search",
        "skills.list",
        "skills.read",
        "web.fetch",
        "web.search",
        "web.crawl",
        "web.extract",
        "web.read",
        "web.find",
    }
)
CODING_TOOL_NAMES = GENERAL_TOOL_NAMES | {"git.status", "tests.run"}
# Read-only research surface with NO agent.research — a delegated child must
# not delegate again. Publishing a user deliverable writes only to the governed
# Artifact Store; it does not mutate the workspace.
RESEARCH_TOOL_NAMES = frozenset(
    {
        "agent.clarify",
        "agent.plan",
        "files.list",
        "files.publish",
        "files.read",
        "files.search",
        "sessions.search",
    }
)


def tool_names_for_profile(profile: ToolProfile) -> frozenset[str]:
    if profile is ToolProfile.GENERAL:
        return GENERAL_TOOL_NAMES
    if profile is ToolProfile.RESEARCH:
        return RESEARCH_TOOL_NAMES
    return CODING_TOOL_NAMES
