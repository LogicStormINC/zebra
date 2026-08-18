from datetime import UTC, datetime, timedelta
from uuid import uuid4

from agent_core.contracts.context_events import ContextContinuationSelectedPayload
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.context_continuation import (
    CloudProviderContinuationArtifact,
    ProviderContinuationRef,
)
from agent_core.domain.identifiers import EventId, SessionId
from agent_core.domain.leases import LeaseFence


def _reference(now: datetime) -> ProviderContinuationRef:
    return ProviderContinuationRef(
        reference_id="provider-ref",
        provider="provider",
        model_name="model",
        capability_version="1",
        source_hash="a" * 64,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
    )


def test_cloud_artifact_keeps_external_scope_and_fence_evidence() -> None:
    now = datetime(2026, 8, 3, tzinfo=UTC)
    session_id = SessionId(uuid4())
    scope = OpaqueAuthorityScope(authority_issuer="issuer", namespace_id="business")
    artifact = CloudProviderContinuationArtifact(
        continuation_id="continuation-1",
        scope=scope,
        deployment_namespace="deployment-a",
        session_id=session_id,
        reference=_reference(now),
        payload_sha256="b" * 64,
        size_bytes=3,
        lifecycle_revision=0,
        selection_event_id=EventId(uuid4()),
        selection_event_sequence=4,
        idempotency_key="provider-continuation:continuation-1",
        accepted_lease=LeaseFence(
            control_plane_epoch=uuid4(),
            fencing_token=2,
            owner_instance_id="worker-a",
        ),
    )

    assert artifact.artifact_id == "continuation-1"
    assert artifact.is_compatible(
        scope=scope,
        session_id=session_id,
        provider="provider",
        model_name="model",
        capability_version="1",
        as_of=now,
    )
    assert not artifact.is_compatible(
        scope=OpaqueAuthorityScope(authority_issuer="other", namespace_id="business"),
        session_id=session_id,
        provider="provider",
        model_name="model",
        capability_version="1",
        as_of=now,
    )


def test_continuation_event_contract_accepts_cloud_scope_evidence() -> None:
    payload = ContextContinuationSelectedPayload(
        attempt_number=1,
        mode="provider_native",
        reason="provider reference accepted",
        artifact_id="continuation-1",
        reference_id="provider-ref",
        provider="provider",
        model_name="model",
        capability_version="1",
        source_hash="a" * 64,
        authority_issuer="issuer",
        namespace_id="business",
        payload_sha256="b" * 64,
    )

    assert payload.authority_issuer == "issuer"
    assert payload.payload_sha256 == "b" * 64
