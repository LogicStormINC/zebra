from datetime import UTC, datetime, timedelta

import pytest
from agent_core.contracts.events import validate_event_payload
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventType
from agent_core.domain.execution_authority import (
    ExecutionAuthorityDecision,
    ExecutionAuthorityLimits,
    ExecutionAuthorityResolutionError,
    ExecutionAuthorityResolutionRequest,
    ExecutionAuthoritySnapshot,
    ExternalAuthorityGrant,
)
from agent_core.domain.identifiers import new_session_id
from pydantic import ValidationError

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def _scope(namespace_id: str = "scope-a") -> OpaqueAuthorityScope:
    return OpaqueAuthorityScope(
        authority_issuer="https://business.example.com",
        namespace_id=namespace_id,
    )


def _limits(**overrides: int | None) -> ExecutionAuthorityLimits:
    values: dict[str, int | None] = {
        "max_concurrent_tasks": 5,
        "max_model_tokens": 100_000,
        "max_runtime_seconds": 3_600,
        "max_tool_calls": 100,
    }
    values.update(overrides)
    return ExecutionAuthorityLimits.model_validate(values)


def _request(
    *,
    grant: ExternalAuthorityGrant | None = None,
    capability_ceiling: tuple[str, ...] | None = None,
) -> ExecutionAuthorityResolutionRequest:
    return ExecutionAuthorityResolutionRequest(
        session_id=new_session_id(),
        attempt_number=1,
        scope=_scope(),
        authority_grant=grant,
        capability_ceiling=capability_ceiling,
        validated_at=NOW,
    )


def _grant(*, revoked: bool = False, expires_at: datetime | None = None) -> ExternalAuthorityGrant:
    return ExternalAuthorityGrant(
        scope=_scope(),
        subject="external-principal-42",
        audience="zebra",
        granted_authorities=("agent.session.read", "agent.task.create", "agent.tool.execute"),
        limits=_limits(),
        issued_at=NOW - timedelta(minutes=1),
        expires_at=expires_at or NOW + timedelta(hours=1),
        source_authority_digest="a" * 64,
        revoked=revoked,
    )


def test_snapshot_is_deterministic_and_event_payload_is_schema_validated() -> None:
    request = _request(
        grant=_grant(),
        capability_ceiling=("agent.tool.execute", "agent.task.create"),
    )
    kwargs = {
        "policy_ref": "policy/worker@1",
        "policy_version": "1",
        "policy_effective_digest": "b" * 64,
    }
    first = ExecutionAuthoritySnapshot.from_request(request, **kwargs)
    second = ExecutionAuthoritySnapshot.from_request(request, **kwargs)

    assert first.snapshot_digest == second.snapshot_digest
    assert first.resolution is ExecutionAuthorityDecision.NARROWED
    assert first.granted_authorities == ("agent.task.create", "agent.tool.execute")
    validated = validate_event_payload(
        EventType.EXECUTION_AUTHORITY_RESOLVED,
        first.to_event_payload(),
    )
    assert ExecutionAuthoritySnapshot.model_validate(validated).snapshot_digest == (
        first.snapshot_digest
    )
    with pytest.raises(ValidationError):
        ExecutionAuthoritySnapshot.model_validate(
            first.model_dump(mode="json") | {"granted_authorities": ["agent.admin"]}
        )


def test_snapshot_rejects_digest_drift_namespace_mismatch_and_expansion() -> None:
    request = _request(grant=_grant())
    snapshot = ExecutionAuthoritySnapshot.from_request(
        request,
        policy_ref="policy/worker@1",
        policy_version="1",
        policy_effective_digest="b" * 64,
    )
    with pytest.raises(ValueError, match="snapshot_digest"):
        ExecutionAuthoritySnapshot.model_validate(
            snapshot.model_dump(mode="json") | {"snapshot_digest": "c" * 64}
        )
    with pytest.raises(ValidationError, match="scope"):
        ExecutionAuthorityResolutionRequest.model_validate(
            request.model_dump(mode="json") | {"scope": _scope("scope-b").model_dump(mode="json")}
        )
    expanded = snapshot.model_copy(
        update={
            "granted_authorities": snapshot.granted_authorities + ("agent.admin",),
            "snapshot_digest": None,
        }
    )
    with pytest.raises(ExecutionAuthorityResolutionError, match="expanded capabilities"):
        snapshot.ensure_not_expanded(expanded)


def test_grant_expiry_revocation_and_secret_material_fail_closed() -> None:
    with pytest.raises(ExecutionAuthorityResolutionError, match="expired"):
        ExecutionAuthoritySnapshot.from_request(
            _request(grant=_grant(expires_at=NOW)),
            policy_ref="policy/worker@1",
            policy_version="1",
            policy_effective_digest="b" * 64,
        )
    with pytest.raises(ExecutionAuthorityResolutionError, match="revoked"):
        ExecutionAuthoritySnapshot.from_request(
            _request(grant=_grant(revoked=True)),
            policy_ref="policy/worker@1",
            policy_version="1",
            policy_effective_digest="b" * 64,
        )
    with pytest.raises(ValidationError):
        ExternalAuthorityGrant.model_validate(
            _grant().model_dump(mode="json") | {"subject": "Bearer abc"}
        )
    with pytest.raises(ValidationError):
        ExecutionAuthoritySnapshot.from_request(
            _request(grant=_grant()),
            policy_ref="policy/current",
            policy_version="1",
            policy_effective_digest="b" * 64,
        )
