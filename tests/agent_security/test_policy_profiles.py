from datetime import UTC, datetime

from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.policies import PolicyDecisionType
from agent_core.domain.tools import ToolCall
from agent_security import LocalPolicyEngine, PolicyProfile, policy_profile


def _tool_call(name: str, arguments: dict[str, object] | None = None) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments or {},
        created_at=datetime(2026, 6, 22, 15, 0, tzinfo=UTC),
    )


def test_legacy_policy_profile_name_is_stable_for_bootstrap_smoke() -> None:
    assert policy_profile() == "local-bootstrap"


def test_read_only_profile_allows_read_tools_and_denies_write_tools() -> None:
    engine = LocalPolicyEngine(profile=PolicyProfile.READ_ONLY)

    assert engine.evaluate_tool_call(_tool_call("files.read")).decision is (
        PolicyDecisionType.ALLOW
    )
    assert engine.evaluate_tool_call(_tool_call("git.status")).decision is (
        PolicyDecisionType.ALLOW
    )
    assert engine.evaluate_tool_call(_tool_call("patch.apply")).decision is (
        PolicyDecisionType.DENY
    )


def test_workspace_write_profile_allows_patch_and_requires_command_approval() -> None:
    engine = LocalPolicyEngine(profile=PolicyProfile.WORKSPACE_WRITE)

    assert engine.evaluate_tool_call(_tool_call("patch.apply")).decision is (
        PolicyDecisionType.ALLOW
    )
    assert engine.evaluate_tool_call(_tool_call("tests.run")).decision is (
        PolicyDecisionType.ALLOW
    )
    assert engine.evaluate_tool_call(_tool_call("command.run")).decision is (
        PolicyDecisionType.REQUIRE_APPROVAL
    )


def test_full_access_profile_allows_known_local_tools() -> None:
    engine = LocalPolicyEngine(profile=PolicyProfile.FULL_ACCESS)

    assert engine.evaluate_tool_call(
        _tool_call("command.run", {"command": ["python", "-m", "pytest"]})
    ).decision is PolicyDecisionType.ALLOW
    assert engine.evaluate_tool_call(_tool_call("tests.run")).policy_profile == (
        "full_access"
    )


def test_full_access_profile_requires_approval_for_shell_interpreter_command() -> None:
    engine = LocalPolicyEngine(profile=PolicyProfile.FULL_ACCESS)

    decision = engine.evaluate_tool_call(
        _tool_call("command.run", {"command": ["sh", "-c", "echo ok"]})
    )

    assert decision.decision is PolicyDecisionType.REQUIRE_APPROVAL
    assert "shell interpreter" in decision.reason


def test_full_access_profile_requires_approval_for_shell_metacharacters() -> None:
    engine = LocalPolicyEngine(profile=PolicyProfile.FULL_ACCESS)

    decision = engine.evaluate_tool_call(
        _tool_call("command.run", {"command": ["python", "-c", "print(1); print(2)"]})
    )

    assert decision.decision is PolicyDecisionType.REQUIRE_APPROVAL
    assert "shell metacharacter" in decision.reason


def test_full_access_profile_requires_approval_for_malformed_command() -> None:
    engine = LocalPolicyEngine(profile=PolicyProfile.FULL_ACCESS)

    decision = engine.evaluate_tool_call(
        _tool_call("command.run", {"command": "python -m pytest"})
    )

    assert decision.decision is PolicyDecisionType.REQUIRE_APPROVAL
    assert "malformed" in decision.reason


def test_unknown_tool_is_denied_for_all_profiles() -> None:
    for profile in PolicyProfile:
        engine = LocalPolicyEngine(profile=profile)

        assert engine.evaluate_tool_call(_tool_call("network.fetch")).decision is (
            PolicyDecisionType.DENY
        )
