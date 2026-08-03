"""Pure transaction helpers for the PostgreSQL continuation aggregate."""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Any, cast
from uuid import UUID

from agent_core.application.session_projection import apply_event as apply_session_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.context_continuation import (
    CloudProviderContinuationArtifact,
    ProviderContinuationRef,
)
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.aggregate_mutation import AdministrativeMutationCAS
from agent_core.ports.provider_continuation_cloud import (
    CloudProviderContinuationCommitResult,
    ProviderContinuationSweepReceipt,
)

from agent_storage.postgres.events import read_event_in_transaction
from agent_storage.postgres.projections import (
    get_session_in_transaction,
    save_session_in_transaction,
)
from agent_storage.postgres.workspaces import (
    get_workspace_in_transaction,
    save_workspace_in_transaction,
)


def save_projections(
    connection: Any,
    namespace: str,
    event: SessionEvent,
    session: Session,
    workspace: WorkspaceProjection,
    conflict_error: type[ValueError],
) -> tuple[Session, WorkspaceProjection]:
    current_session = get_session_in_transaction(connection, namespace, event.session_id)
    current_workspace = get_workspace_in_transaction(connection, namespace, event.session_id)
    if current_session is None or current_workspace is None:
        raise conflict_error(
            "continuation commit requires existing Session and Workspace projections"
        )
    if current_session.current_sequence == event.sequence:
        if current_workspace.current_sequence != event.sequence:
            raise conflict_error("canonical continuation projections are incomplete")
        return current_session, current_workspace
    if current_session.current_sequence != event.sequence - 1:
        raise conflict_error("Session projection does not precede the continuation Event")
    expected_session = apply_session_event(current_session, event)
    expected_workspace = apply_workspace_event(current_workspace, event)
    if session != expected_session or workspace != expected_workspace:
        raise conflict_error("continuation projections are not derived from the canonical Event")
    return (
        save_session_in_transaction(connection, namespace, expected_session),
        save_workspace_in_transaction(connection, namespace, expected_workspace),
    )


def replay_commit(
    connection: Any,
    namespace: str,
    row: dict[str, Any],
    request_digest: str,
    conflict_error: type[ValueError],
) -> CloudProviderContinuationCommitResult:
    if row["request_hash"] != request_digest:
        raise conflict_error("continuation idempotency key was reused with different meaning")
    if row["selection_event_id"] is None:
        raise conflict_error("continuation row has no canonical Event binding")
    event = read_event_in_transaction(connection, namespace, row["selection_event_id"])
    if event is None:
        raise conflict_error("continuation row references a missing canonical Event")
    stored_session = get_session_in_transaction(connection, namespace, event.session_id)
    stored_workspace = get_workspace_in_transaction(connection, namespace, event.session_id)
    if stored_session is None or stored_workspace is None:
        raise conflict_error("canonical continuation projections are incomplete")
    return CloudProviderContinuationCommitResult(
        artifact=artifact_from_row(row),
        event=event,
        session=stored_session,
        workspace=stored_workspace,
    )


def artifact_from_row(row: dict[str, Any]) -> CloudProviderContinuationArtifact:
    return CloudProviderContinuationArtifact(
        continuation_id=row["continuation_id"],
        scope=OpaqueAuthorityScope(
            authority_issuer=row["authority_issuer"],
            namespace_id=row["namespace_id"],
        ),
        deployment_namespace=row["deployment_namespace"],
        session_id=SessionId(row["session_id"]),
        reference=ProviderContinuationRef(
            reference_id=row["reference_id"],
            provider=row["provider"],
            model_name=row["model_name"],
            capability_version=row["capability_version"],
            source_hash=row["source_hash"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
        ),
        payload_sha256=row["payload_sha256"],
        size_bytes=row["size_bytes"],
        lifecycle_revision=row["lifecycle_revision"],
        selection_event_id=row["selection_event_id"],
        selection_event_sequence=row["selection_event_sequence"],
        idempotency_key=row["idempotency_key"],
        accepted_lease=LeaseFence(
            control_plane_epoch=row["accepted_lease_epoch"],
            fencing_token=row["accepted_lease_fencing_token"],
            owner_instance_id=row["accepted_lease_owner_instance_id"],
        ),
        deleted_at=row["deleted_at"],
    )


def validate_selection_payload(
    event: SessionEvent,
    scope: OpaqueAuthorityScope,
    continuation_id: str,
    reference: ProviderContinuationRef,
    payload: bytes,
    conflict_error: type[ValueError],
) -> None:
    expected = {
        "mode": "provider_native",
        "artifact_id": continuation_id,
        "reference_id": reference.reference_id,
        "provider": reference.provider,
        "model_name": reference.model_name,
        "capability_version": reference.capability_version,
        "source_hash": reference.source_hash,
        "authority_issuer": scope.authority_issuer,
        "namespace_id": scope.namespace_id,
        "payload_sha256": sha256(payload).hexdigest(),
    }
    for key, value in expected.items():
        if event.payload.get(key) != value:
            raise conflict_error(
                f"continuation Event field {key} does not match the stored payload"
            )


def scope_matches(scope: OpaqueAuthorityScope, expected: tuple[str, str]) -> bool:
    return scope.scope_key == expected


def lock_expected_stream(
    connection: Any,
    namespace: str,
    session_id: SessionId,
    expected: int,
    conflict_error: type[ValueError],
) -> None:
    row = connection.execute(
        """
        SELECT current_version FROM session_streams
        WHERE deployment_namespace = %s AND session_id = %s
        FOR UPDATE
        """,
        (namespace, session_id),
    ).fetchone()
    if row is None or row["current_version"] != expected:
        raise conflict_error("continuation stream revision is stale")


def required_text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be blank")
    return normalized


def request_hash(
    scope: OpaqueAuthorityScope,
    continuation_id: str,
    session_id: SessionId,
    reference: ProviderContinuationRef,
    payload: bytes,
    maximum_ttl_seconds: int | None,
    event: SessionEvent,
) -> str:
    return digest(
        {
            "scope": scope.scope_key,
            "continuation_id": continuation_id,
            "session_id": str(session_id),
            "reference": reference.model_dump(mode="json"),
            "payload_sha256": sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "maximum_ttl_seconds": maximum_ttl_seconds,
            "event_type": event.event_type.value,
            "event_sequence": event.sequence,
            "idempotency_key": event.idempotency_key,
        }
    )


def delete_hash(scope: OpaqueAuthorityScope, continuation_id: str, idempotency_key: str) -> str:
    return digest(
        {"scope": scope.scope_key, "continuation_id": continuation_id, "key": idempotency_key}
    )


def sweep_hash(
    scope: OpaqueAuthorityScope,
    operation_id: UUID,
    operator_id: str,
    reason: str,
    limit: int,
    as_of: datetime,
) -> str:
    return digest(
        {
            "scope": scope.scope_key,
            "operation_id": str(operation_id),
            "operator_id": operator_id,
            "reason": reason,
            "limit": limit,
            "as_of": as_of.isoformat(),
        }
    )


def digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return sha256(encoded).hexdigest()


def find_mutation(
    connection: Any, row: dict[str, Any], kind: str, key: str
) -> dict[str, Any] | None:
    return cast(
        "dict[str, Any] | None",
        connection.execute(
            """
        SELECT * FROM provider_continuation_mutations
        WHERE deployment_namespace = %s AND continuation_id = %s
          AND operation_kind = %s AND idempotency_key = %s
        """,
            (row["deployment_namespace"], row["continuation_id"], kind, key),
        ).fetchone(),
    )


def assert_management_boundary(
    connection: Any,
    namespace: str,
    authority: AdministrativeMutationCAS,
    conflict_error: type[ValueError],
) -> None:
    row = connection.execute(
        """
        SELECT current_version FROM session_streams
        WHERE deployment_namespace = %s AND session_id = %s
        FOR SHARE
        """,
        (namespace, authority.session_id),
    ).fetchone()
    if row is None or row["current_version"] != authority.expected_stream_revision:
        raise conflict_error("management CAS stream revision is stale")


def sweep_receipt(
    row: dict[str, Any], conflict_error: type[ValueError]
) -> ProviderContinuationSweepReceipt:
    ids = row["expired_continuation_ids"]
    if not isinstance(ids, list):
        raise conflict_error("management audit receipt is malformed")
    return ProviderContinuationSweepReceipt(
        operation_id=row["operation_id"],
        authority_issuer=row["authority_issuer"],
        namespace_id=row["namespace_id"],
        deployment_namespace=row["deployment_namespace"],
        expired_continuation_ids=tuple(str(item) for item in ids),
        recorded_at=row["recorded_at"],
    )
