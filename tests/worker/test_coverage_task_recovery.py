"""Recover strict identity from durable bytes and recheck replacement grants."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest
from agent_core.application.coverage_semantic import semantic_check
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.coverage_contracts import (
    CoverageContract,
    CoverageRefusalReason,
    CoverageScope,
)
from agent_core.domain.coverage_execution import CoverageExecutionBudget
from agent_core.domain.coverage_task_admission import CoverageTaskAdmission
from agent_core.domain.events import SessionEvent
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.leases import LeaseFence, WorkerLease
from agent_security.host_grant import JwtAlgorithm, VerifiedHostGrant
from agent_storage import LocalArtifactPayloadReader, SQLiteArtifactPayloadStore
from zebra_agent_api.session_binding import _build_binding_snapshot
from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.execution_finalization import WorkerExecutionError
from zebra_agent_worker.execution_recovery import recover_execution_inputs
from zebra_agent_worker.recovery import RecoveredSession
from zebra_agent_worker.task_recovery import RecoveredTask, apply_bound_host_context, recover_task


def identity(profile: str = "review-profile") -> CoverageTaskAdmission:
    return CoverageTaskAdmission(
        contract=CoverageContract(
            scope=CoverageScope(
                timezone="UTC",
                from_inclusive=datetime(2029, 1, 1, tzinfo=UTC),
                to_exclusive=datetime(2030, 1, 1, tzinfo=UTC),
            ),
            checks=(semantic_check(profile).contract_check,),
        ),
        history_ref="history-1",
        model_profile=profile,
        execution_budget=CoverageExecutionBudget(max_attempts=100, max_input_bytes=1000),
        max_model_calls=100,
        max_model_tokens=1000,
        max_runtime_seconds=60,
    )


def context() -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id="grant-1",
        host_app_id="trench",
        namespace_id="user-1",
        workspace_ref="workspace-1",
        resource_refs=(
            HostResourceRef(type="trench.history", id="history-1"),
            HostResourceRef(type="principal", id="user"),
            HostResourceRef(type="thread", id="thread-1"),
        ),
        scopes=("history.read", "history.snapshot.write"),
        limits=HostTechnicalLimits(
            max_runtime_seconds=60,
            max_model_tokens=1000,
            max_artifact_bytes=10000,
        ),
        origin="https://trench.example",
        policy_version="v1",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


def events(tmp_path: Path, *, strict: bool = True) -> list[SessionEvent]:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="task",
            user_input="review history-1",
            workspace_root=tmp_path,
            coverage_admission=identity() if strict else None,
            host_context=context() if strict else None,
            model_profile="deepseek-v4-flash-executor-v1",
            reasoning_effort="none",
        )
    )
    return [SessionEvent.model_validate_json(event.model_dump_json()) for event in bootstrap.events]


def recover(raw: list[SessionEvent], tmp_path: Path) -> RecoveredTask:
    return recover_task(
        raw,
        workspace=rebuild_workspace(raw),
        fallback_title="fallback",
        attachment_reader=LocalArtifactPayloadReader(
            SQLiteArtifactPayloadStore(tmp_path / "db.sqlite")
        ),
    )


def binding(host: HostContextEnvelope):
    return _build_binding_snapshot(
        "11111111-1111-1111-1111-111111111111",
        host_context=host,
        verified_host_grant=VerifiedHostGrant(
            host, host.grant_id, JwtAlgorithm.RS256, host.origin, "user"
        ),
        definition_snapshot_digest="a" * 64,
    )


def test_recovers_fresh_typed_identity_and_preserves_ordinary_model(tmp_path: Path) -> None:
    task = recover(events(tmp_path), tmp_path)
    assert task.coverage_admission == identity()
    assert isinstance(task.coverage_admission, CoverageTaskAdmission)
    assert task.model_invocation_policy is not None
    assert task.model_invocation_policy.profile_id != task.coverage_admission.model_profile
    assert recover(events(tmp_path, strict=False), tmp_path).coverage_admission is None


def test_same_prepared_identity_is_acceptable(tmp_path: Path) -> None:
    raw = events(tmp_path)
    newer = raw[-1].model_copy(
        update={
            "sequence": 3,
            "payload": raw[-1].payload | {"coverage_admission": identity().model_dump(mode="json")},
        }
    )
    task = recover([*raw, newer], tmp_path)
    assert task.coverage_admission == identity()
    newer.payload["coverage_admission"]["max_model_calls"] = 0
    with pytest.raises(ValueError):
        recover([*raw, newer], tmp_path)


@pytest.mark.parametrize("change", ["missing", "null", "profile", "history", "budget", "contract"])
def test_later_prepared_cannot_drop_or_change_strict_identity(tmp_path: Path, change: str) -> None:
    raw = events(tmp_path)
    payload = dict(raw[-1].payload)
    if change == "missing":
        del payload["coverage_admission"]
    elif change == "null":
        payload["coverage_admission"] = None
    elif change == "profile":
        payload["coverage_admission"] = identity("other-valid-review").model_dump(mode="json")
    else:
        updated = identity().model_dump(mode="json")
        if change == "history":
            updated["history_ref"] = "other"
        elif change == "budget":
            updated["max_model_calls"] = 99
        else:
            updated["contract"]["contract_revision"] = 2
        payload["coverage_admission"] = updated
    newer = raw[-1].model_copy(update={"sequence": 3, "payload": payload})
    with pytest.raises(ValueError, match="dropped or changed strict"):
        recover([*raw, newer], tmp_path)


def test_legacy_prepared_can_precede_explicit_strict_identity(tmp_path: Path) -> None:
    raw = events(tmp_path, strict=False)
    strict = events(tmp_path)[-1]
    strict = strict.model_copy(update={"session_id": raw[0].session_id, "sequence": 3})
    assert recover([*raw, strict], tmp_path).coverage_admission == identity()


@pytest.mark.parametrize(
    "change", ["digest", "profile", "budget", "scope", "resource", "expired", "host_missing"]
)
def test_recovery_refuses_tampered_raw_identity_or_host(tmp_path: Path, change: str) -> None:
    raw = events(tmp_path)
    payload = raw[-1].payload
    if change == "digest":
        payload["coverage_admission"]["contract"]["checks"][0]["definition_digest"] = "a" * 64
    elif change == "profile":
        payload["coverage_admission"]["model_profile"] = "other"
    elif change == "budget":
        payload["coverage_admission"]["max_model_tokens"] = 1001
    elif change == "scope":
        payload["host_context"]["scopes"] = ["history.read"]
    elif change == "resource":
        payload["host_context"]["resource_refs"] = [{"type": "trench.history", "id": "other"}]
    elif change == "expired":
        payload["host_context"]["expires_at"] = "2000-01-01T00:00:00Z"
    else:
        del payload["host_context"]
    with pytest.raises(ValueError):
        recover(raw, tmp_path)


def test_recovery_uses_current_clock_not_task_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = events(tmp_path)
    expiry = HostContextEnvelope.model_validate(raw[-1].payload["host_context"]).expires_at
    assert expiry is not None

    class ExpiredClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return expiry

    monkeypatch.setattr("zebra_agent_worker.task_recovery.datetime", ExpiredClock)
    with pytest.raises(ValueError, match="future Host expiry"):
        recover(raw, tmp_path)


def test_binding_replacement_retains_strict_identity(tmp_path: Path) -> None:
    task = recover(events(tmp_path), tmp_path)
    host = context().model_copy(update={"grant_id": "renewed"})
    bound = apply_bound_host_context(task, binding(host))
    assert bound.host_context == host
    assert bound.coverage_admission == task.coverage_admission
    assert apply_bound_host_context(bound, None) == bound


@pytest.mark.parametrize(
    "update",
    [
        {"resource_refs": (HostResourceRef(type="trench.history", id="other"),)},
        {"scopes": ("history.read",)},
        {"scopes": ("history.snapshot.write",)},
        {"expires_at": datetime(2000, 1, 1, tzinfo=UTC)},
        {"expires_at": None},
        {
            "limits": HostTechnicalLimits(
                max_runtime_seconds=59, max_model_tokens=1000, max_artifact_bytes=10000
            )
        },
        {
            "limits": HostTechnicalLimits(
                max_runtime_seconds=60, max_model_tokens=999, max_artifact_bytes=10000
            )
        },
    ],
)
def test_bound_grant_replacement_refuses_wrong_resource_revoked_scope_and_budget(
    tmp_path: Path,
    update: dict[str, object],
) -> None:
    task = recover(events(tmp_path), tmp_path)
    # Correct binding digest is insufficient: strict identity must still match.
    replacement = context().model_copy(update=update)
    with pytest.raises(ValueError):
        apply_bound_host_context(task, binding(replacement))


def test_binding_without_host_cannot_drop_strict_identity(tmp_path: Path) -> None:
    task = recover(events(tmp_path), tmp_path)
    current = binding(context())
    missing = current.model_copy(
        update={
            "host_capability": current.host_capability.model_copy(update={"host_context": None}),
        }
    )
    with pytest.raises(ValueError, match="Host context"):
        apply_bound_host_context(task, missing)
    with pytest.raises(ValueError, match="Host context"):
        apply_bound_host_context(replace(task, host_context=None), None)


def test_no_binding_still_revalidates_clock_and_forged_nested_identity(tmp_path: Path) -> None:
    task = recover(events(tmp_path), tmp_path)
    with pytest.raises(ValueError, match="future Host expiry"):
        apply_bound_host_context(
            replace(
                task,
                host_context=context().model_copy(
                    update={
                        "expires_at": datetime(2000, 1, 1, tzinfo=UTC),
                    }
                ),
            ),
            None,
        )
    assert task.coverage_admission is not None
    forged = task.coverage_admission.model_copy(
        update={
            "execution_budget": task.coverage_admission.execution_budget.model_copy(
                update={"unknown": "not dropped"}
            ),
        }
    )
    with pytest.raises(ValueError, match="unknown attributes"):
        apply_bound_host_context(replace(task, coverage_admission=forged), binding(context()))


@pytest.mark.parametrize("strict", [True, False])
@pytest.mark.parametrize("cloud_deployment", [True, False])
def test_actual_execution_recovery_refuses_unconfigured_strict_before_workspace(
    tmp_path: Path,
    strict: bool,
    cloud_deployment: bool,
) -> None:
    raw = events(tmp_path, strict=strict)
    now = datetime.now(UTC)
    session_id = raw[0].session_id
    claimed = ClaimedSession(
        recovery=RecoveredSession(
            session=rebuild_session(raw),
            workspace=rebuild_workspace(raw),
            event_count=len(raw),
            last_sequence=raw[-1].sequence,
            is_terminal=False,
        ),
        lease=WorkerLease(
            session_id=session_id,
            fence=LeaseFence(
                control_plane_epoch=UUID("11111111-1111-1111-1111-111111111111"),
                fencing_token=1,
                owner_instance_id="test-worker",
            ),
            acquired_at=now,
            heartbeat_at=now,
            expires_at=now + timedelta(minutes=1),
        ),
    )
    resolver = Mock()
    resolver.resolve.return_value = tmp_path / "resolved"
    inputs = dict(
        claimed=claimed,
        session_id=session_id,
        started_at=now,
        cloud_deployment=cloud_deployment,
        cloud_provider_continuation_factory=None,
        provider_continuation_store=Mock(),
        control_service=Mock(),
        recovery_service=Mock(),
        event_store=Mock(list_for_session=Mock(return_value=raw)),
        context_lifecycle_store=Mock(get_active_capsule=Mock(return_value=None)),
        handoff_gate=Mock(recover=Mock(return_value=None)),
        artifact_payload_reader=LocalArtifactPayloadReader(
            SQLiteArtifactPayloadStore(tmp_path / "db.sqlite")
        ),
        workspace_resolver=resolver,
        execution_input_reader=(lambda _lease: raw) if cloud_deployment else None,
    )
    # Exercise actual Task parsing and the shared entry, with only storage and
    # infrastructure stubbed. No dispatcher or fake configured capability.
    if strict:
        with pytest.raises(
            WorkerExecutionError, match="^strict coverage refused: coverage_unsupported$"
        ) as refused:
            recover_execution_inputs(**inputs)
        assert refused.value.coverage_refusal_reason is CoverageRefusalReason.UNSUPPORTED
        resolver.resolve.assert_not_called()
    else:
        recovered = recover_execution_inputs(**inputs)
        assert recovered.claimed is claimed
        assert recovered.session_events == raw
        assert recovered.task.coverage_admission is None
        assert recovered.task.workspace_root == tmp_path / "resolved"
        resolver.resolve.assert_called_once_with(str(tmp_path), session_id=session_id)
    if cloud_deployment:
        inputs["event_store"].list_for_session.assert_not_called()
