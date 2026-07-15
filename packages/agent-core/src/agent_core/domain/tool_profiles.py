from enum import StrEnum


class ToolProfile(StrEnum):
    GENERAL = "general"
    CODING = "coding"


GENERAL_TOOL_NAMES = frozenset(
    {
        "agent.clarify",
        "agent.plan",
        "agent.research",
        "command.run",
        "files.read",
        "files.search",
        "patch.apply",
        "web.fetch",
        "web.search",
    }
)
CODING_TOOL_NAMES = GENERAL_TOOL_NAMES | {"git.status", "tests.run"}


def tool_names_for_profile(profile: ToolProfile) -> frozenset[str]:
    return GENERAL_TOOL_NAMES if profile is ToolProfile.GENERAL else CODING_TOOL_NAMES
