from enum import StrEnum


class ToolProfile(StrEnum):
    GENERAL = "general"
    CODING = "coding"


GENERAL_TOOL_NAMES = frozenset(
    {"agent.research", "command.run", "files.read", "patch.apply", "web.fetch"}
)
CODING_TOOL_NAMES = GENERAL_TOOL_NAMES | {"git.status", "tests.run"}


def tool_names_for_profile(profile: ToolProfile) -> frozenset[str]:
    return GENERAL_TOOL_NAMES if profile is ToolProfile.GENERAL else CODING_TOOL_NAMES
