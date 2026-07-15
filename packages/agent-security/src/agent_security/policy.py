from dataclasses import dataclass
from enum import StrEnum

from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall

from agent_security.external_policy import (
    blocked_route_reason,
    external_approval_decision,
)
from agent_security.mcp_proxy_policy import (
    ToolEgressMetadata,
    ToolEgressRoute,
    classify_tool_egress,
)
from agent_security.network_profile import DEFAULT_NETWORK_PROFILE, NetworkProfile


class PolicyProfile(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    FULL_ACCESS = "full_access"


class ApprovalRisk(StrEnum):
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ApprovalRequest:
    tool_name: str
    policy_profile: str
    risk: ApprovalRisk
    reason: str
    scope: tuple[str, ...]
    route: ToolEgressRoute | None = None
    target: str | None = None
    network_profile: str | None = None

    def __post_init__(self) -> None:
        if not self.tool_name.strip():
            raise ValueError("approval request tool_name must not be blank")
        if not self.policy_profile.strip():
            raise ValueError("approval request policy_profile must not be blank")
        if not self.reason.strip():
            raise ValueError("approval request reason must not be blank")
        for item in self.scope:
            if not item.strip():
                raise ValueError("approval request scope must not contain blanks")
        if self.target is not None and not self.target.strip():
            raise ValueError("approval request target must not be blank")
        if self.network_profile is not None and not self.network_profile.strip():
            raise ValueError("approval request network_profile must not be blank")


READ_ONLY_TOOLS = frozenset(
    {
        "agent.clarify",
        "agent.plan",
        "agent.research",
        "files.read",
        "files.search",
        "git.status",
        "skills.list",
        "skills.read",
        "sessions.search",
    }
)
WORKSPACE_WRITE_TOOLS = READ_ONLY_TOOLS | frozenset({"patch.apply", "tests.run"})
FULL_ACCESS_TOOLS = WORKSPACE_WRITE_TOOLS | frozenset({"command.run"})
SHELL_EXECUTABLES = frozenset({"bash", "fish", "powershell", "pwsh", "sh", "zsh"})
SHELL_INJECTION_MARKERS = ("&&", "||", "$(", "`", ";", "|", ">", "<")
SENSITIVE_PATH_MARKERS = (".env", "credential", "id_rsa", "private_key", "secret", "token")
EXFILTRATION_COMMANDS = frozenset({"curl", "nc", "netcat", "scp", "wget"})
PATH_ARGUMENTS_BY_TOOL = {
    "command.run": ("cwd",),
    "files.read": ("path",),
    "files.search": ("path",),
    "git.status": ("cwd",),
}


@dataclass(frozen=True)
class LocalPolicyEngine:
    profile: PolicyProfile = PolicyProfile.READ_ONLY
    network_profile: NetworkProfile = DEFAULT_NETWORK_PROFILE
    web_search_endpoint: str | None = None

    def evaluate_tool_call(self, tool_call: ToolCall) -> PolicyDecision:
        tool_name = tool_call.name
        path_risk_reason = _path_risk_reason(tool_call)
        if path_risk_reason is not None:
            return _deny(self.profile, path_risk_reason)
        egress = classify_tool_egress(
            tool_call,
            network_profile=self.network_profile,
            web_search_endpoint=self.web_search_endpoint,
        )
        if egress.route is ToolEgressRoute.BLOCKED:
            return _deny(self.profile, blocked_route_reason(egress))
        if egress.route in (ToolEgressRoute.MCP_PROXY, ToolEgressRoute.WEB_GATEWAY):
            return external_approval_decision(
                policy_profile=self.profile.value,
                tool_call=tool_call,
                egress=egress,
            )
        if self.profile is PolicyProfile.READ_ONLY:
            return _decision_for_read_only(tool_name, self.profile)
        if self.profile is PolicyProfile.WORKSPACE_WRITE:
            return _decision_for_workspace_write(tool_name, self.profile)
        return _decision_for_full_access(tool_call, self.profile)


def policy_profile() -> str:
    return "local-bootstrap"


def build_approval_request(
    tool_call: ToolCall,
    decision: PolicyDecision,
    *,
    network_profile: NetworkProfile = DEFAULT_NETWORK_PROFILE,
    web_search_endpoint: str | None = None,
) -> ApprovalRequest | None:
    if decision.decision is not PolicyDecisionType.REQUIRE_APPROVAL:
        return None
    egress = classify_tool_egress(
        tool_call,
        network_profile=network_profile,
        web_search_endpoint=web_search_endpoint,
    )
    return ApprovalRequest(
        tool_name=tool_call.name,
        policy_profile=decision.policy_profile,
        risk=_approval_risk(decision.reason),
        reason=decision.reason,
        scope=_approval_scope(tool_call, egress),
        route=egress.route,
        target=egress.target,
        network_profile=egress.network_profile,
    )


def _decision_for_read_only(
    tool_name: str,
    profile: PolicyProfile,
) -> PolicyDecision:
    if tool_name in READ_ONLY_TOOLS:
        return _allow(profile, f"{tool_name} is allowed by read-only policy on local route")
    return _deny(profile, f"{tool_name} is not allowed by read-only policy")


def _decision_for_workspace_write(
    tool_name: str,
    profile: PolicyProfile,
) -> PolicyDecision:
    if tool_name in WORKSPACE_WRITE_TOOLS:
        return _allow(
            profile,
            f"{tool_name} is allowed by workspace-write policy on local route",
        )
    if tool_name == "command.run":
        return _approval(
            profile,
            "command.run requires approval in workspace-write policy on local route",
        )
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
        return _allow(profile, f"{tool_name} is allowed by full-access policy on local route")
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
    if executable in EXFILTRATION_COMMANDS:
        return "command.run requires approval for network-capable data transfer"
    command_text = " ".join(command_parts)
    if _contains_sensitive_marker(command_text):
        return "command.run requires approval for sensitive path reference"
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


def _contains_sensitive_marker(value: str) -> bool:
    normalized = value.lower()
    return any(marker in normalized for marker in SENSITIVE_PATH_MARKERS)


def _approval_risk(reason: str) -> ApprovalRisk:
    normalized = reason.lower()
    if "sensitive" in normalized or "data transfer" in normalized:
        return ApprovalRisk.HIGH
    return ApprovalRisk.MEDIUM


def _approval_scope(
    tool_call: ToolCall,
    egress: ToolEgressMetadata,
) -> tuple[str, ...]:
    entries = [f"tool:{tool_call.name}"]
    entries.append(f"route:{egress.route.value}")
    entries.append(f"network_profile:{egress.network_profile}")
    if egress.target is not None:
        entries.append(f"target:{egress.target}")
    command = tool_call.arguments.get("command")
    if isinstance(command, list | tuple) and command:
        executable = command[0]
        if isinstance(executable, str) and executable.strip():
            entries.append(f"command:{executable.strip()}")
    cwd = tool_call.arguments.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        entries.append(f"cwd:{cwd.strip()}")
    return tuple(entries)


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
