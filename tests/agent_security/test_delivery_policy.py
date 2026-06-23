from agent_security import CommitPolicy, DeliveryDecisionType, PullRequestPolicy


def test_commit_policy_allows_full_access_sessions() -> None:
    decision = CommitPolicy().evaluate("full_access")

    assert decision.decision is DeliveryDecisionType.ALLOW
    assert decision.policy_profile == "full_access"


def test_commit_policy_denies_non_full_access_sessions() -> None:
    decision = CommitPolicy().evaluate("workspace_write")

    assert decision.decision is DeliveryDecisionType.DENY
    assert decision.policy_profile == "workspace_write"
    assert decision.reason == "commit requires full_access session policy"


def test_commit_policy_defaults_missing_profile_to_workspace_write() -> None:
    decision = CommitPolicy().evaluate(None)

    assert decision.decision is DeliveryDecisionType.DENY
    assert decision.policy_profile == "workspace_write"


def test_pull_request_policy_allows_full_access_sessions() -> None:
    decision = PullRequestPolicy().evaluate("full_access")

    assert decision.decision is DeliveryDecisionType.ALLOW
    assert decision.policy_profile == "full_access"


def test_pull_request_policy_denies_non_full_access_sessions() -> None:
    decision = PullRequestPolicy().evaluate("workspace_write")

    assert decision.decision is DeliveryDecisionType.DENY
    assert decision.policy_profile == "workspace_write"
    assert decision.reason == "pull request requires full_access session policy"
