from __future__ import annotations

import os
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.governed_memories import (
    GovernedMemoryEntry,
    canonical_governed_memory_content_hash,
    canonical_governed_memory_creation_key,
)
from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_core.domain.memory_delivery import (
    MemoryDeliveryCertainty,
    MemoryDeliveryScope,
    MemoryDeliveryScopeState,
)
from agent_storage import (
    MemoryDeliveryConflictError,
    PostgresMemoryDeliveryLedger,
    apply_postgres_migrations,
)
from agent_storage.postgres.governed_memory_rows import memory_values
from psycopg import sql
from psycopg.conninfo import make_conninfo

NOW = datetime(2026, 8, 2, 8, 0, tzinfo=UTC)


@dataclass
class FakeProviderIndex:
    """A deterministic stand-in for an upstream commit with a lost response."""

    refs: set[str] = field(default_factory=set)

    def publish_before_response_loss(self) -> str:
        provider_ref = f"provider-orphan-{len(self.refs) + 1}"
        self.refs.add(provider_ref)
        return provider_ref


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run the reset alternative")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str]:
    schema = f"mem0_reset_alt_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(isolated)
    yield isolated
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def ledger(dsn: str) -> PostgresMemoryDeliveryLedger:
    return PostgresMemoryDeliveryLedger(dsn, deployment_namespace="reset-alt-test")


def scope(*, generation: int = 1, revision: int = 0) -> MemoryDeliveryScope:
    return MemoryDeliveryScope(
        deployment_namespace="reset-alt-test",
        scope_digest="a" * 64,
        generation=generation,
        revision=revision,
    )


def test_logical_generation_reset_fences_hits_and_deletes_known_mapping(
    dsn: str,
    ledger: PostgresMemoryDeliveryLedger,
) -> None:
    current_scope = scope()
    retained_id = MemoryId(uuid4())
    retained_digest = _insert_authority(dsn, retained_id, label="retained")
    retained_ref = _publish(ledger, retained_id, retained_digest, current_scope, "provider-known")
    assert ledger.revalidate_search_hits(current_scope, [(retained_id, retained_ref)])

    delete = ledger.enqueue_delete(
        retained_id,
        memory_revision=3,
        content_digest=retained_digest,
        scope=current_scope,
    )
    delete_claim = ledger.claim_next(owner="reset-alt-delete", scope=current_scope)
    assert delete_claim is not None
    assert delete_claim.operation.idempotency_key == delete.idempotency_key
    ledger.mark_in_flight(delete_claim)
    ledger.complete(delete_claim, certainty=MemoryDeliveryCertainty.APPLIED)
    assert ledger.get_mapping(retained_id, scope=current_scope) is None

    fenced_id = MemoryId(uuid4())
    fenced_digest = _insert_authority(dsn, fenced_id, label="fenced")
    fenced_ref = _publish(ledger, fenced_id, fenced_digest, current_scope, "provider-fenced")
    assert ledger.get_mapping(fenced_id, scope=current_scope) is not None

    ledger.quarantine_scope(current_scope, reason_code="logical_reset")
    next_scope = ledger.ensure_scope(scope(generation=2))
    assert next_scope.state is MemoryDeliveryScopeState.ACTIVE
    assert ledger.revalidate_search_hits(current_scope, [(fenced_id, fenced_ref)]) == ()
    assert ledger.revalidate_search_hits(next_scope, [(fenced_id, fenced_ref)]) == ()
    with pytest.raises(MemoryDeliveryConflictError, match="not active"):
        ledger.enqueue_delete(
            fenced_id,
            memory_revision=3,
            content_digest=fenced_digest,
            scope=current_scope,
        )


def test_unknown_publish_orphan_is_not_recoverable_from_ledger(
    dsn: str,
    ledger: PostgresMemoryDeliveryLedger,
) -> None:
    provider = FakeProviderIndex()
    current_scope = scope()
    memory_id = MemoryId(uuid4())
    operation = ledger.enqueue_publish(
        memory_id,
        memory_revision=1,
        content_digest="b" * 64,
        scope=current_scope,
    )
    claim = ledger.claim_next(owner="reset-alt-publisher", scope=current_scope)
    assert claim is not None
    ledger.mark_in_flight(claim)
    orphan_ref = provider.publish_before_response_loss()
    uncertain = ledger.mark_uncertain(claim, reason_code="response_lost")
    assert uncertain.certainty is MemoryDeliveryCertainty.UNKNOWN

    quarantined = ledger.get_scope(scope_digest=current_scope.scope_digest, generation=1)
    assert quarantined is not None and quarantined.state is MemoryDeliveryScopeState.QUARANTINED
    next_scope = ledger.ensure_scope(scope(generation=2))
    assert provider.refs == {orphan_ref}
    assert ledger.get_mapping(memory_id, scope=current_scope) is None
    assert ledger.revalidate_search_hits(next_scope, [(memory_id, orphan_ref)]) == ()
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            """
            SELECT provider_ref FROM memory_delivery_operations
            WHERE deployment_namespace = %s AND idempotency_key = %s
            """,
            ("reset-alt-test", operation.idempotency_key),
        ).fetchone()
    assert row is not None and row[0] is None


def _publish(
    ledger: PostgresMemoryDeliveryLedger,
    memory_id: MemoryId,
    content_digest: str,
    current_scope: MemoryDeliveryScope,
    provider_ref: str,
) -> str:
    operation = ledger.enqueue_publish(
        memory_id,
        memory_revision=2,
        content_digest=content_digest,
        scope=current_scope,
    )
    claim = ledger.claim_next(owner="reset-alt-publisher", scope=current_scope)
    assert claim is not None and claim.operation.idempotency_key == operation.idempotency_key
    ledger.mark_in_flight(claim)
    completed = ledger.complete(
        claim,
        certainty=MemoryDeliveryCertainty.APPLIED,
        provider_ref=provider_ref,
    )
    assert completed.certainty is MemoryDeliveryCertainty.APPLIED
    return provider_ref


def _insert_authority(dsn: str, memory_id: MemoryId, *, label: str) -> str:
    record = MemoryRecord(
        memory_id=memory_id,
        memory_type=MemoryType.PREFERENCE,
        text=f"authoritative fact {label}",
        confidence=0.9,
        status=MemoryStatus.CONFIRMED,
        visibility=MemoryVisibility.REPO,
        repo_id=f"zebra-agent-{label}",
        created_at=NOW,
        updated_at=NOW,
    )
    content_digest = canonical_governed_memory_content_hash(record)
    entry = GovernedMemoryEntry(
        deployment_namespace="reset-alt-test",
        record=record,
        revision=2,
        creation_key=canonical_governed_memory_creation_key(record),
        content_digest=content_digest,
    )
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """
            INSERT INTO governed_memory_records (
                deployment_namespace, memory_id, revision, memory_type, text,
                confidence, status, visibility, tenant_id, user_id, repo_id,
                source_session_id, source_event_start, source_event_end,
                source_commit_sha, superseded_by, expires_at, created_at,
                updated_at, creation_key, content_digest, provenance_digest
            ) VALUES ("""
            + ", ".join(["%s"] * 22)
            + ")",
            memory_values("reset-alt-test", entry),
        )
    return content_digest
