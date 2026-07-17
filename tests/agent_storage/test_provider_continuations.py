from datetime import UTC, datetime, timedelta

import pytest
from agent_core.domain.context_continuation import ProviderContinuationRef
from agent_storage import SQLiteProviderContinuationStore


def test_provider_continuation_is_tenant_and_capability_scoped(tmp_path) -> None:
    store = SQLiteProviderContinuationStore(tmp_path / "continuations.db")
    now = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)
    reference = ProviderContinuationRef(
        reference_id="response-1",
        provider="openai",
        model_name="gpt-5",
        capability_version="responses.compact.v1",
        source_hash="a" * 64,
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    artifact = store.store(
        tenant_id="tenant-a",
        session_id="session-a",
        reference=reference,
        opaque_payload=b"encrypted-provider-state",
        maximum_ttl_seconds=3600,
    )

    assert (
        store.load_compatible(
            artifact.artifact_id,
            tenant_id="tenant-a",
            provider="openai",
            model_name="gpt-5",
            capability_version="responses.compact.v1",
            as_of=now,
        ).opaque_payload
        == b"encrypted-provider-state"
    )  # type: ignore[union-attr]
    assert (
        store.load_compatible(
            artifact.artifact_id,
            tenant_id="tenant-b",
            provider="openai",
            model_name="gpt-5",
            capability_version="responses.compact.v1",
            as_of=now,
        )
        is None
    )
    assert (
        store.load_compatible(
            artifact.artifact_id,
            tenant_id="tenant-a",
            provider="openai",
            model_name="gpt-5",
            capability_version="responses.compact.v2",
            as_of=now,
        )
        is None
    )


def test_provider_continuation_expiry_and_delete_remove_payload(tmp_path) -> None:
    store = SQLiteProviderContinuationStore(tmp_path / "continuations.db")
    now = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)
    reference = ProviderContinuationRef(
        reference_id="response-1",
        provider="openai",
        model_name="gpt-5",
        source_hash="a" * 64,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    artifact = store.store(
        tenant_id="tenant-a",
        session_id="session-a",
        reference=reference,
        opaque_payload=b"opaque",
    )

    assert store.sweep_expired(as_of=now + timedelta(minutes=5)) == [artifact.artifact_id]
    assert (
        store.load_compatible(
            artifact.artifact_id,
            tenant_id="tenant-a",
            provider="openai",
            model_name="gpt-5",
            capability_version="1",
            as_of=now,
        )
        is None
    )
    deleted = store.delete(artifact.artifact_id, tenant_id="tenant-a")
    assert deleted is not None and deleted.deleted_at is not None


def test_provider_continuation_requires_bounded_ttl(tmp_path) -> None:
    store = SQLiteProviderContinuationStore(tmp_path / "continuations.db")
    with pytest.raises(ValueError, match="requires an expiry"):
        store.store(
            tenant_id="tenant-a",
            session_id="session-a",
            reference=ProviderContinuationRef(
                reference_id="response-1",
                provider="openai",
                model_name="gpt-5",
                source_hash="a" * 64,
            ),
            opaque_payload=b"opaque",
        )
