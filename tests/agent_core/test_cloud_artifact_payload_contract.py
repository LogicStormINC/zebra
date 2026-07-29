from datetime import UTC, datetime, timedelta
from hashlib import sha256
from inspect import Parameter, signature
from typing import get_type_hints
from uuid import uuid4

import pytest
from agent_core.domain import (
    ArtifactEventBinding,
    ArtifactManagementContext,
    ArtifactMetadataQuery,
    ArtifactObjectExpectation,
    ArtifactObjectReceipt,
    ArtifactReconcileQuery,
    ArtifactReserveRequest,
    CloudArtifactPayloadLifecycleStatus,
    CloudArtifactPayloadRecord,
)
from agent_core.domain.artifact_objects import ArtifactObjectExpectation as DirectExpectation
from agent_core.domain.cloud_artifact_requests import (
    ArtifactManagementContext as DirectManagementContext,
)
from agent_core.domain.identifiers import ArtifactId, EventId, SessionId
from agent_core.ports import (
    AdministrativeMutationCAS,
    ArtifactObjectStorePort,
    ArtifactPayloadStorePort,
    CloudArtifactPayloadStorePort,
    WorkerMutationAuthority,
)
from pydantic import ValidationError

NOW = datetime(2026, 7, 29, tzinfo=UTC)
PAYLOAD = b"zebra"
DIGEST = sha256(PAYLOAD).hexdigest()


def _artifact_id() -> ArtifactId:
    return ArtifactId(uuid4())


def _session_id() -> SessionId:
    return SessionId(uuid4())


def _expectation(*, artifact_id: ArtifactId | None = None) -> ArtifactObjectExpectation:
    return ArtifactObjectExpectation(
        deployment_namespace="cloud-a",
        artifact_id=artifact_id or _artifact_id(),
        sha256=DIGEST,
        size_bytes=len(PAYLOAD),
    )


def _receipt(*, artifact_id: ArtifactId | None = None) -> ArtifactObjectReceipt:
    return ArtifactObjectReceipt(
        expectation=_expectation(artifact_id=artifact_id),
        object_version="version-1",
        verified_at=NOW,
    )


def _reservation(*, artifact_id: ArtifactId | None = None) -> ArtifactReserveRequest:
    return ArtifactReserveRequest(
        artifact_id=artifact_id or _artifact_id(),
        session_id=_session_id(),
        intended_event_sequence=4,
        kind="tool_output",
        mime_type="text/plain",
        sha256=DIGEST,
        size_bytes=len(PAYLOAD),
        idempotency_key="artifact:4",
        retained_until=NOW + timedelta(days=1),
        created_at=NOW,
    )


def _event_binding(reservation: ArtifactReserveRequest) -> ArtifactEventBinding:
    return ArtifactEventBinding(
        session_id=reservation.session_id,
        event_id=EventId(uuid4()),
        sequence=reservation.intended_event_sequence,
        artifact_uri=f"artifact://{reservation.artifact_id}",
    )


def test_cloud_lifecycle_statuses_are_exact() -> None:
    assert tuple(CloudArtifactPayloadLifecycleStatus) == (
        CloudArtifactPayloadLifecycleStatus.STAGED,
        CloudArtifactPayloadLifecycleStatus.FINALIZED,
        CloudArtifactPayloadLifecycleStatus.COMPENSATED,
        CloudArtifactPayloadLifecycleStatus.PRUNING,
        CloudArtifactPayloadLifecycleStatus.PRUNED,
    )
    assert "missing" not in CloudArtifactPayloadLifecycleStatus
    assert "active" not in CloudArtifactPayloadLifecycleStatus


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", ""),
        ("mime_type", " text/plain"),
        ("idempotency_key", "artifact:4 "),
        ("sha256", DIGEST.upper()),
        ("size_bytes", -1),
        ("intended_event_sequence", -1),
        ("created_at", datetime(2026, 7, 29)),
        ("retained_until", NOW - timedelta(seconds=1)),
    ],
)
def test_reservation_rejects_noncanonical_inputs(field: str, value: object) -> None:
    values = _reservation().model_dump()
    values[field] = value

    with pytest.raises(ValidationError):
        ArtifactReserveRequest.model_validate(values)


def test_reservation_is_frozen_and_forbids_extra_fields() -> None:
    reservation = _reservation()

    with pytest.raises(ValidationError):
        reservation.kind = "other"
    with pytest.raises(ValidationError):
        ArtifactReserveRequest.model_validate({**reservation.model_dump(), "provider": "minio"})


def test_lifecycle_record_requires_exact_state_evidence() -> None:
    reservation = _reservation()
    staged = CloudArtifactPayloadRecord(
        deployment_namespace="cloud-a",
        reservation=reservation,
        lifecycle_status=CloudArtifactPayloadLifecycleStatus.STAGED,
        lifecycle_revision=0,
    )
    receipt = _receipt(artifact_id=reservation.artifact_id)
    finalized = staged.model_copy(
        update={
            "lifecycle_status": CloudArtifactPayloadLifecycleStatus.FINALIZED,
            "lifecycle_revision": 2,
            "event_binding": _event_binding(reservation),
            "object_receipt": receipt,
            "finalized_at": NOW,
        }
    )

    assert CloudArtifactPayloadRecord.model_validate(finalized.model_dump()).uri == (
        f"artifact://{reservation.artifact_id}"
    )
    with pytest.raises(ValidationError, match="finalized proof"):
        CloudArtifactPayloadRecord.model_validate(
            staged.model_copy(
                update={"lifecycle_status": CloudArtifactPayloadLifecycleStatus.FINALIZED}
            ).model_dump()
        )

    with pytest.raises(ValidationError, match="cannot be compensated"):
        CloudArtifactPayloadRecord.model_validate(
            finalized.model_copy(update={"compensated_at": NOW}).model_dump()
        )
    with pytest.raises(ValidationError, match="only compensation evidence"):
        CloudArtifactPayloadRecord.model_validate(
            staged.model_copy(
                update={
                    "lifecycle_status": CloudArtifactPayloadLifecycleStatus.COMPENSATED,
                    "event_binding": _event_binding(reservation),
                    "compensated_at": NOW,
                }
            ).model_dump()
        )


def test_lifecycle_record_binds_event_and_object_to_reservation() -> None:
    reservation = _reservation()
    receipt = _receipt(artifact_id=reservation.artifact_id)
    values = {
        "deployment_namespace": "cloud-a",
        "reservation": reservation,
        "lifecycle_status": CloudArtifactPayloadLifecycleStatus.FINALIZED,
        "lifecycle_revision": 2,
        "event_binding": _event_binding(reservation),
        "object_receipt": receipt,
        "finalized_at": NOW,
    }

    finalized = CloudArtifactPayloadRecord.model_validate(values)
    wrong_event = _event_binding(reservation).model_copy(
        update={"artifact_uri": f"artifact://{_artifact_id()}"}
    )
    with pytest.raises(ValidationError, match="Event binding"):
        CloudArtifactPayloadRecord.model_validate({**values, "event_binding": wrong_event})
    wrong_object = receipt.model_copy(
        update={
            "expectation": receipt.expectation.model_copy(
                update={"deployment_namespace": "cloud-b"}
            )
        }
    )
    with pytest.raises(ValidationError, match="object receipt"):
        CloudArtifactPayloadRecord.model_validate({**values, "object_receipt": wrong_object})
    with pytest.raises(ValidationError, match="prune-start"):
        CloudArtifactPayloadRecord.model_validate(
            finalized.model_copy(
                update={"lifecycle_status": CloudArtifactPayloadLifecycleStatus.PRUNING}
            ).model_dump()
        )


def test_management_context_is_explicit_and_auditable() -> None:
    context = ArtifactManagementContext(
        operation_id=uuid4(),
        operator_id="retention-worker",
        reason="expired payload sweep",
    )

    assert context.operator_id == "retention-worker"
    with pytest.raises(ValidationError):
        ArtifactManagementContext.model_validate(
            {**context.model_dump(), "operator_id": " retention-worker"}
        )


def test_metadata_and_reconcile_queries_validate_trust_boundary() -> None:
    ArtifactMetadataQuery(
        deployment_namespace="cloud-a",
        artifact_id=_artifact_id(),
        session_id=_session_id(),
    )
    ArtifactReconcileQuery(older_than=NOW, limit=100)

    with pytest.raises(ValidationError):
        ArtifactMetadataQuery(
            deployment_namespace=" cloud-a",
            artifact_id=_artifact_id(),
            session_id=_session_id(),
        )
    with pytest.raises(ValidationError):
        ArtifactReconcileQuery(older_than=datetime(2026, 7, 29), limit=0)


def test_cloud_ports_require_worker_or_management_authority() -> None:
    worker_methods = (
        "reserve_for_worker",
        "record_object_for_worker",
        "finalize_for_worker",
        "compensate_for_worker",
        "begin_prune_for_worker",
        "complete_prune_for_worker",
    )
    management_methods = (
        "finalize_reconciled",
        "compensate_reconciled",
        "begin_retention_prune",
        "complete_reconciled_prune",
        "list_reconcilable",
    )

    for method_name in worker_methods:
        method = getattr(CloudArtifactPayloadStorePort, method_name)
        assert signature(method).parameters["authority"].default is Parameter.empty
        assert get_type_hints(method)["authority"] is WorkerMutationAuthority
    for method_name in management_methods:
        method = getattr(CloudArtifactPayloadStorePort, method_name)
        assert signature(method).parameters["authority"].default is Parameter.empty
        assert get_type_hints(method)["authority"] is AdministrativeMutationCAS
        assert get_type_hints(method)["audit"] is ArtifactManagementContext


def test_cloud_contract_exports_do_not_replace_local_port() -> None:
    assert ArtifactObjectExpectation is DirectExpectation
    assert ArtifactManagementContext is DirectManagementContext
    assert CloudArtifactPayloadStorePort is not ArtifactPayloadStorePort
    assert set(signature(ArtifactPayloadStorePort.store_payload).parameters) == {
        "self",
        "payload",
        "artifact_id",
    }
    assert set(ArtifactObjectStorePort.__dict__) >= {
        "put_if_absent",
        "verify",
        "read_verified",
        "delete_if_version",
    }
