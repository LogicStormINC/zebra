"""Strict identity validation is structural evidence, not dispatch/JWT proof."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from agent_core.application.coverage_admission import validate_coverage_admission
from agent_core.application.coverage_semantic import semantic_check
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.contracts.events import TaskPreparedPayload, validate_event_payload
from agent_core.contracts.task_prepared import TaskPreparedPayload as SplitPayload
from agent_core.domain.coverage_contracts import CoverageContract, CoverageScope
from agent_core.domain.coverage_execution import CoverageExecutionBudget
from agent_core.domain.coverage_task_admission import CoverageTaskAdmission
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.host_authority import (
    MAX_MODEL_TOKENS,
    MAX_RUNTIME_SECONDS,
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)

NOW = datetime(2030, 1, 1, tzinfo=UTC)


def admission() -> CoverageTaskAdmission:
    return CoverageTaskAdmission(
        contract=CoverageContract(
            scope=CoverageScope(
                timezone="UTC",
                from_inclusive=NOW - timedelta(days=1),
                to_exclusive=NOW,
            ),
            checks=(semantic_check("review-profile").contract_check,),
        ),
        history_ref="history-1",
        model_profile="review-profile",
        execution_budget=CoverageExecutionBudget(max_attempts=100, max_input_bytes=1000),
        max_model_calls=100,
        max_model_tokens=1000,
        max_runtime_seconds=60,
    )


def host() -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id="grant-1",
        host_app_id="trench",
        namespace_id="user-1",
        workspace_ref="workspace-1",
        resource_refs=(HostResourceRef(type="trench.history", id="history-1"),),
        scopes=("history.read", "history.snapshot.write"),
        limits=HostTechnicalLimits(
            max_runtime_seconds=60,
            max_model_tokens=1000,
            max_artifact_bytes=10000,
        ),
        origin="https://trench.example",
        policy_version="v1",
        expires_at=NOW + timedelta(seconds=1),
    )


def test_legacy_payload_is_exactly_unchanged() -> None:
    assert TaskPreparedPayload is SplitPayload
    result = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="legacy",
            user_input="exhaustive semantic review history-1",
            workspace_root=Path("/tmp/w"),
            created_at=datetime(2000, 1, 1, tzinfo=UTC),
        )
    )
    assert result.events[2].payload == {
        "title": "legacy",
        "user_input": "exhaustive semantic review history-1",
        "workspace_root": "/tmp/w",
        "policy_profile": None,
        "tool_profile": "general",
        "network_profile": "none",
        "network_allowlist": [],
        "mcp_allowlist": [],
        "skill_components": [],
        "max_attempts": 1,
        "max_model_calls": None,
        "max_tool_calls": None,
    }
    assert "coverage_admission" not in TaskPreparedPayload(
        title="legacy",
        user_input="go",
        coverage_admission=None,
    ).model_dump(mode="json")
    assert all(event.created_at == datetime(2000, 1, 1, tzinfo=UTC) for event in result.events)


def test_bootstrap_raw_roundtrip_and_reviewer_profile_independence() -> None:
    identity = admission()
    result = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="strict",
            user_input="review",
            workspace_root=Path("/tmp/w"),
            coverage_admission=identity,
            host_context=host().model_copy(
                update={
                    "expires_at": datetime.now(UTC) + timedelta(minutes=5),
                }
            ),
            created_at=NOW,
            model_profile="deepseek-v4-flash-executor-v1",
            reasoning_effort="none",
        )
    )
    restored = SessionEvent.model_validate_json(result.events[2].model_dump_json())
    assert restored.payload["coverage_admission"] == identity.model_dump(mode="json")
    assert all("coverage_admission" not in event.payload for event in result.events[:2])
    parsed = TaskPreparedPayload.model_validate(restored.payload)
    assert parsed.coverage_admission == identity
    assert parsed.coverage_admission is not identity
    assert parsed.model_profile != identity.model_profile
    assert all(event.created_at == NOW for event in result.events)
    assert validate_coverage_admission(identity, host_context=host(), now=NOW) == identity


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_profile", "other"),
        ("model_profile", " "),
        ("model_profile", 123),
        ("history_ref", "other"),
        ("history_ref", " history-1"),
        ("max_model_calls", True),
        ("max_model_calls", "100"),
        ("max_model_calls", 1.0),
        ("max_model_calls", 0),
        ("max_model_calls", 1_000_001),
        ("max_model_tokens", False),
        ("max_model_tokens", 0),
        ("max_model_tokens", 1001),
        ("max_model_tokens", MAX_MODEL_TOKENS + 1),
        ("max_runtime_seconds", True),
        ("max_runtime_seconds", "60"),
        ("max_runtime_seconds", 0),
        ("max_runtime_seconds", 61),
        ("max_runtime_seconds", MAX_RUNTIME_SECONDS + 1),
        ("execution_budget", {"max_attempts": 0, "max_input_bytes": 1000}),
        ("execution_budget", {"max_attempts": True, "max_input_bytes": 1000}),
        ("execution_budget", {"max_attempts": 1, "max_input_bytes": -1}),
        ("extra", "unknown"),
    ],
)
def test_rejects_malformed_or_tampered_identity(field: str, value: object) -> None:
    raw = admission().model_dump(mode="json")
    raw[field] = value
    with pytest.raises(ValueError):
        validate_coverage_admission(raw, host_context=host(), now=NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "other"),
        ("version", "2"),
        ("kind", "program"),
        ("definition_digest", "a" * 64),
        ("extra", "unknown"),
    ],
)
def test_rejects_tampered_check_tuple_and_digest(field: str, value: object) -> None:
    raw = admission().model_dump(mode="json")
    raw["contract"]["checks"][0][field] = value
    with pytest.raises(ValueError):
        validate_coverage_admission(raw, host_context=host(), now=NOW)


def test_requires_only_one_published_check() -> None:
    for checks in ([], [semantic_check("other").contract_check.model_dump(mode="json")]):
        raw = admission().model_dump(mode="json")
        raw["contract"]["checks"] = checks
        with pytest.raises(ValueError):
            validate_coverage_admission(raw, host_context=host(), now=NOW)
    raw = admission().model_dump(mode="json")
    extra = deepcopy(raw["contract"]["checks"][0])
    extra["id"] = "another"
    raw["contract"]["checks"].append(extra)
    with pytest.raises(ValueError):
        validate_coverage_admission(raw, host_context=host(), now=NOW)


@pytest.mark.parametrize(
    "update",
    [
        {"expires_at": None},
        {"expires_at": NOW},
        {"expires_at": NOW - timedelta(seconds=1)},
        {"scopes": ("history.read",)},
        {"scopes": ("history.snapshot.write",)},
        {"resource_refs": [{"type": "trench.source", "id": "history-1"}]},
        {"resource_refs": [{"type": "trench.history", "id": "other"}]},
        {
            "resource_refs": [
                {"type": "trench.history", "id": "history-1"},
                {"type": "trench.history", "id": "other"},
            ]
        },
        {
            "limits": {
                "max_runtime_seconds": 59,
                "max_model_tokens": 1000,
                "max_artifact_bytes": 10000,
            }
        },
        {
            "limits": {
                "max_runtime_seconds": 60,
                "max_model_tokens": 999,
                "max_artifact_bytes": 10000,
            }
        },
    ],
)
def test_rejects_wrong_or_expired_host(update: dict[str, object]) -> None:
    raw = host().model_dump(mode="python") | update
    with pytest.raises(ValueError):
        validate_coverage_admission(admission(), host_context=raw, now=NOW)


def test_requires_host_and_aware_clock() -> None:
    with pytest.raises(ValueError, match="Host context"):
        validate_coverage_admission(admission(), host_context=None, now=NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_coverage_admission(admission(), host_context=host(), now=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="invalid payload"):
        validate_event_payload(
            EventType.TASK_PREPARED,
            {
                "title": "strict",
                "user_input": "review",
                "coverage_admission": admission(),
            },
        )


def test_backdated_bootstrap_rejects_currently_expired_host_before_any_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual_now = datetime.now(UTC)
    expired_host = host().model_copy(update={"expires_at": actual_now - timedelta(minutes=1)})
    backdated_created_at = actual_now - timedelta(minutes=2)

    def unexpected_event(**kwargs: object) -> None:
        pytest.fail("Events must not be built before admission validation")

    monkeypatch.setattr(SessionEvent, "create", unexpected_event)
    with pytest.raises(ValueError, match="future Host expiry"):
        SessionBootstrapService().build(
            SessionBootstrapCommand(
                title="strict",
                user_input="review",
                workspace_root=Path("/tmp/w"),
                coverage_admission=admission(),
                host_context=expired_host,
                created_at=backdated_created_at,
            )
        )


@pytest.mark.parametrize(
    "location", ["admission", "contract", "scope", "check", "budget", "host", "limits", "resource"]
)
@pytest.mark.parametrize("extra", [False, True])
def test_forged_typed_copies_and_nested_objects_are_revalidated(location: str, extra: bool) -> None:
    identity, context = admission(), host()
    targets = {
        "admission": identity,
        "contract": identity.contract,
        "scope": identity.contract.scope,
        "check": identity.contract.checks[0],
        "budget": identity.execution_budget,
        "host": context,
        "limits": context.limits,
        "resource": context.resource_refs[0],
    }
    fields = {
        "admission": ("max_model_calls", False),
        "contract": ("mode", "sample"),
        "scope": ("timezone", "invalid"),
        "check": ("definition_digest", "bad"),
        "budget": ("max_attempts", False),
        "host": ("expires_at", None),
        "limits": ("max_model_tokens", False),
        "resource": ("resource_type", "other"),
    }
    target = targets[location]
    field, value = ("unknown", "must not disappear") if extra else fields[location]
    # Forge stored fields just as nested model_copy/model_construct can do.
    object.__setattr__(target, field, value)
    with pytest.raises(ValueError):
        validate_coverage_admission(identity, host_context=context, now=NOW)
    # Shape-only contracts allow absent expiry or another resource type; the
    # application checks those against the strict request and current clock.
    if extra or location not in {"host", "resource"}:
        with pytest.raises(ValueError):
            TaskPreparedPayload(
                title="strict",
                user_input="review",
                coverage_admission=identity,
                host_context=context,
            )


def test_copy_and_construct_do_not_bypass_bootstrap() -> None:
    for identity in (
        admission().model_copy(update={"max_model_tokens": "1000"}),
        CoverageTaskAdmission.model_construct(**(admission().__dict__ | {"max_model_calls": 0})),
        admission().model_copy(
            update={
                "execution_budget": admission().execution_budget.model_copy(
                    update={"unknown": "must not disappear"},
                )
            }
        ),
    ):
        with pytest.raises(ValueError):
            SessionBootstrapService().build(
                SessionBootstrapCommand(
                    title="strict",
                    user_input="review",
                    workspace_root=Path("/tmp/w"),
                    coverage_admission=identity,
                    host_context=host(),
                    created_at=NOW,
                )
            )
