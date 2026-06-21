from dataclasses import dataclass
from enum import StrEnum

from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall


class PolicyProfile(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    FULL_ACCESS = "full_access"


READ_ONLY_TOOLS = frozenset({"files.read", "git.status"})
WORKSPACE_WRITE_TOOLS = READ_ONLY_TOOLS | frozenset({"patch.apply", "tests.run"})
FULL_ACCESS_TOOLS = WORKSPACE_WRITE_TOOLS | frozenset({"command.run"})
SHELL_EXECUTABLES = frozenset({"bash", "fish", "powershell", "pwsh", "sh", "zsh"})
SHELL_INJECTION_MARKERS = ("&&", "||", "$(", "`", ";", "|", ">", "<")
PATH_ARGUMENTS_BY_TOOL = {
    "command.run": ("cwd",),
    "files.read": ("path",),
    "git.status": ("cwd",),
}


@dataclass(frozen=True)
class LocalPolicyEngine:
    profile: PolicyProfile = PolicyProfile.READ_ONLY

    def evaluate_tool_call(self, tool_call: ToolCall) -> PolicyDecision:
        tool_name = tool_call.name
        path_risk_reason = _path_risk_reason(tool_call)
        if path_risk_reason is not None:
            return _deny(self.profile, path_risk_reason)
        if self.profile is PolicyProfile.READ_ONLY:
            return _decision_for_read_only(tool_name, self.profile)
        if self.profile is PolicyProfile.WORKSPACE_WRITE:
            return _decision_for_workspace_write(tool_name, self.profile)
        return _decision_for_full_access(tool_call, self.profile)


def policy_profile() -> str:
    return "local-bootstrap"


def _decision_for_read_only(
    tool_name: str,
    profile: PolicyProfile,
) -> PolicyDecision:
    if tool_name in READ_ONLY_TOOLS:
        return _allow(profile, f"{tool_name} is allowed by read-only policy")
    return _deny(profile, f"{tool_name} is not allowed by read-only policy")


def _decision_for_workspace_write(
    tool_name: str,
    profile: PolicyProfile,
) -> PolicyDecision:
    if tool_name in WORKSPACE_WRITE_TOOLS:
        return _allow(profile, f"{tool_name} is allowed by workspace-write policy")
    if tool_name == "command.run":
        return _approval(profile, "command.run requires approval in workspace-write policy")
    return _deny(profile, f"{tool_name} is not a known workspace-write tool")


def _decision_for_full_access(
    tool_call: ToolCall,
    profile: PolicyProfile,
) -> PolicyDecision:
    tool_name = tool_call.name
    if tool_name == "command.run":
        risk_reason = _command_risk_reason(tool_call)
        if risk_reason is not None:
            return _approval(profile, risk_reason)
    if tool_name in FULL_ACCESS_TOOLS:
        return _allow(profile, f"{tool_name} is allowed by full-access policy")
    return _deny(profile, f"{tool_name} is not a known full-access tool")


def _command_risk_reason(tool_call: ToolCall) -> str | None:
    raw_command = tool_call.arguments.get("command")
    if not isinstance(raw_command, list | tuple) or not raw_command:
        return "command.run requires approval because command arguments are malformed"
    command_parts = []
    for part in raw_command:
        if not isinstance(part, str) or not part.strip():
            return "command.run requires approval because command arguments are malformed"
        command_parts.append(part.strip())
    executable = command_parts[0].rsplit("/", maxsplit=1)[-1].lower()
    if executable in SHELL_EXECUTABLES:
        return "command.run requires approval for shell interpreter execution"
    command_text = " ".join(command_parts)
    if any(marker in command_text for marker in SHELL_INJECTION_MARKERS):
        return "command.run requires approval for shell metacharacter usage"
    return None


def _path_risk_reason(tool_call: ToolCall) -> str | None:
    for argument_name in PATH_ARGUMENTS_BY_TOOL.get(tool_call.name, ()):
        raw_path = tool_call.arguments.get(argument_name)
        if raw_path is None:
            continue
        if not isinstance(raw_path, str):
            return f"{tool_call.name} path argument {argument_name} must be a string"
        if _is_unsafe_relative_path(raw_path):
            return f"{tool_call.name} path argument {argument_name} escapes workspace"
    if tool_call.name == "patch.apply":
        return _patch_path_risk_reason(tool_call)
    return None


def _patch_path_risk_reason(tool_call: ToolCall) -> str | None:
    raw_patch = tool_call.arguments.get("patch")
    if not isinstance(raw_patch, str):
        return "patch.apply patch argument must be a string"
    for line in raw_patch.splitlines():
        if not line.startswith(("--- ", "+++ ")):
            continue
        raw_path = line[4:].strip()
        if raw_path == "/dev/null":
            continue
        normalized = _normalize_patch_path(raw_path)
        if _is_unsafe_relative_path(normalized):
            return "patch.apply contains a path outside the workspace"
    return None


def _normalize_patch_path(raw_path: str) -> str:
    if raw_path.startswith(("a/", "b/")):
        return raw_path[2:]
    return raw_path


def _is_unsafe_relative_path(raw_path: str) -> bool:
    stripped = raw_path.strip()
    if not stripped:
        return True
    if stripped.startswith(("/", "\\")):
        return True
    parts = stripped.replace("\\", "/").split("/")
    return any(part == ".." for part in parts)


def _allow(profile: PolicyProfile, reason: str) -> PolicyDecision:
    return PolicyDecision(
        decision=PolicyDecisionType.ALLOW,
        reason=reason,
        policy_profile=profile.value,
    )


def _approval(profile: PolicyProfile, reason: str) -> PolicyDecision:
    return PolicyDecision(
        decision=PolicyDecisionType.REQUIRE_APPROVAL,
        reason=reason,
        policy_profile=profile.value,
    )


def _deny(profile: PolicyProfile, reason: str) -> PolicyDecision:
    return PolicyDecision(
        decision=PolicyDecisionType.DENY,
        reason=reason,
        policy_profile=profile.value,
    )
