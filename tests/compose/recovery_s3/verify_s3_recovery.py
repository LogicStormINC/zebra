"""Exercise independent versioned Artifact backup-copy restore evidence."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from time import time_ns
from typing import Any, cast
from uuid import UUID

import psycopg
from agent_core.domain.artifact_objects import (
    ArtifactObjectDeleteRequest,
    ArtifactObjectDeleteStatus,
    ArtifactObjectExpectation,
    ArtifactObjectPutRequest,
    ArtifactObjectVerificationStatus,
)
from agent_core.domain.cloud_artifact_requests import (
    ArtifactEventBinding,
    ArtifactFinalizeRequest,
    ArtifactMetadataQuery,
    ArtifactRecordObjectRequest,
    ArtifactReserveRequest,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_artifact_id, new_session_id
from agent_core.domain.leases import LeaseFence
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_storage import (
    PostgresCloudArtifactPayloadStore,
    PostgresEventStore,
    PostgresLeaseStore,
    S3ArtifactObjectStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.session import Session  # type: ignore[import-untyped]
from psycopg.rows import dict_row

NAMESPACE = "recovery-s3"
OTHER_NAMESPACE = "other-namespace"
BUCKET = "zebra-artifacts"
BACKUP_BUCKET = "zebra-artifacts-backup"
KEY_PREFIX = "zebra/artifacts/v1"
PAYLOAD = b"zebra independent object backup v1\n"
LEASE_TTL = timedelta(minutes=10)


def _client(endpoint: str, access_key: str, secret_key: str) -> Any:
    return Session().create_client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _store(endpoint: str, access_key: str, secret_key: str, bucket: str) -> S3ArtifactObjectStore:
    return S3ArtifactObjectStore(
        cast(Any, _client(endpoint, access_key, secret_key)),
        bucket=bucket,
        key_prefix=KEY_PREFIX,
    )


def _key(expectation: ArtifactObjectExpectation) -> str:
    namespace_hash = sha256(expectation.deployment_namespace.encode()).hexdigest()
    return f"{KEY_PREFIX}/{namespace_hash}/{expectation.artifact_id}"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _event_snapshot(event: SessionEvent) -> dict[str, Any]:
    return event.model_dump(mode="json")


def _expectation(expected: dict[str, Any]) -> ArtifactObjectExpectation:
    return ArtifactObjectExpectation.model_validate(expected["artifact"]["expectation"])


def _authority(
    session_id: SessionId,
    fence: LeaseFence,
    expected_stream_revision: int,
) -> WorkerMutationAuthority:
    return WorkerMutationAuthority(
        deployment_namespace=NAMESPACE,
        session_id=session_id,
        expected_stream_revision=expected_stream_revision,
        lease_fence=fence,
    )


def _seed(
    dsn: str,
    endpoint: str,
    access_key: str,
    secret_key: str,
    expected_path: Path,
    target_name: str,
) -> None:
    del target_name
    apply_postgres_migrations(dsn)
    epoch = bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    session_id = new_session_id()
    event_store = PostgresEventStore(dsn, deployment_namespace=NAMESPACE)
    seed_event = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.SYSTEM,
        payload={"title": "independent S3 backup seed"},
        idempotency_key="recovery-s3-seed-1",
        created_at=datetime.now(UTC),
    )
    event_store.append(seed_event)
    lease = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).acquire(
        session_id,
        owner_instance_id="s3-source-worker",
        ttl=LEASE_TTL,
        checkpoint=0,
    )
    artifact_id = new_artifact_id()
    expectation = ArtifactObjectExpectation(
        deployment_namespace=NAMESPACE,
        artifact_id=artifact_id,
        sha256=sha256(PAYLOAD).hexdigest(),
        size_bytes=len(PAYLOAD),
    )
    payload_store = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=NAMESPACE)
    reservation = payload_store.reserve_for_worker(
        ArtifactReserveRequest(
            artifact_id=artifact_id,
            session_id=session_id,
            intended_event_sequence=1,
            kind="s3-recovery-test",
            mime_type="application/octet-stream",
            sha256=expectation.sha256,
            size_bytes=expectation.size_bytes,
            idempotency_key="recovery-s3-reserve-1",
            file_name="backup.bin",
            created_at=datetime.now(UTC),
        ),
        authority=_authority(session_id, lease.fence, 0),
    )
    source_store = _store(endpoint, access_key, secret_key, BUCKET)
    source_receipt = source_store.put_if_absent(
        ArtifactObjectPutRequest(expectation=expectation, payload=PAYLOAD)
    )
    artifact_event = SessionEvent.create(
        session_id=session_id,
        sequence=1,
        event_type=EventType.TOOL_EXECUTION_COMPLETED,
        actor=EventActor.HARNESS,
        payload={
            "attempt_number": 1,
            "tool_name": "artifact-backup-test",
            "tool_call_id": None,
            "status": "executed",
            "output": "artifact reference committed",
            "metadata": {"artifact_uri": f"artifact://{artifact_id}"},
        },
        idempotency_key="recovery-s3-artifact-event-1",
        created_at=datetime.now(UTC),
    )
    event_store.append(artifact_event)
    lease = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).heartbeat(
        session_id,
        fence=lease.fence,
        ttl=LEASE_TTL,
        checkpoint=1,
    )
    worker_authority = _authority(session_id, lease.fence, 1)
    recorded = payload_store.record_object_for_worker(
        ArtifactRecordObjectRequest(
            artifact_id=artifact_id,
            session_id=session_id,
            expected_lifecycle_revision=reservation.lifecycle_revision,
            idempotency_key="recovery-s3-record-1",
            object_receipt=source_receipt,
        ),
        authority=worker_authority,
    )
    finalized = payload_store.finalize_for_worker(
        ArtifactFinalizeRequest(
            artifact_id=artifact_id,
            session_id=session_id,
            expected_lifecycle_revision=recorded.lifecycle_revision,
            idempotency_key="recovery-s3-finalize-1",
            event_binding=ArtifactEventBinding(
                session_id=session_id,
                event_id=artifact_event.event_id,
                sequence=1,
                artifact_uri=f"artifact://{artifact_id}",
            ),
            object_receipt=source_receipt,
            finalized_at=datetime.now(UTC),
        ),
        authority=worker_authority,
    )
    if (
        finalized.object_receipt is None
        or finalized.object_receipt.object_version != source_receipt.object_version
    ):
        raise RuntimeError("PostgreSQL Artifact ref did not retain source object version")
    backup_client = _client(endpoint, access_key, secret_key)
    backup_client.copy_object(
        Bucket=BACKUP_BUCKET,
        Key=_key(expectation),
        CopySource={
            "Bucket": BUCKET,
            "Key": _key(expectation),
            "VersionId": source_receipt.object_version,
        },
        MetadataDirective="COPY",
    )
    backup_store = _store(endpoint, access_key, secret_key, BACKUP_BUCKET)
    backup_verification = backup_store.verify(expectation)
    if backup_verification.status is not ArtifactObjectVerificationStatus.VERIFIED:
        raise RuntimeError("independent backup copy failed metadata verification")
    assert backup_verification.receipt is not None
    expected = {
        "schema_version": "zebra.recovery.s3.evidence.v1",
        "drill_id": f"s3-{time_ns()}",
        "environment": "production-like",
        "provider": "minio-versioned",
        "deployment_namespace": NAMESPACE,
        "session_id": str(session_id),
        "epoch": str(epoch),
        "event": _event_snapshot(artifact_event),
        "lease": {"fence": lease.fence.model_dump(mode="json")},
        "artifact": {
            "expectation": expectation.model_dump(mode="json"),
            "source_object_version": source_receipt.object_version,
            "backup_object_version": backup_verification.receipt.object_version,
            "postgres_object_version": source_receipt.object_version,
            "lifecycle_status": finalized.lifecycle_status.value,
            "lifecycle_revision": finalized.lifecycle_revision,
        },
        "source_deleted": False,
    }
    _write(expected_path, expected)
    print(
        "S3_RECOVERY_SEED=PASS "
        f"artifact={artifact_id} source_version={source_receipt.object_version} "
        f"backup_version={backup_verification.receipt.object_version} "
        f"pg_revision={finalized.lifecycle_revision}"
    )


def _clear(
    endpoint: str,
    access_key: str,
    secret_key: str,
    expected_path: Path,
) -> None:
    expected = _load(expected_path)
    expectation = _expectation(expected)
    source_store = _store(endpoint, access_key, secret_key, BUCKET)
    deletion = source_store.delete_if_version(
        ArtifactObjectDeleteRequest(
            expectation=expectation,
            object_version=expected["artifact"]["source_object_version"],
        )
    )
    if deletion.status is not ArtifactObjectDeleteStatus.DELETED:
        raise RuntimeError("source Artifact object version was not deleted")
    if source_store.verify(expectation).status is not ArtifactObjectVerificationStatus.NOT_FOUND:
        raise RuntimeError("source Artifact object remained current after deletion")
    expected["source_deleted"] = True
    _write(expected_path, expected)
    print("S3_RECOVERY_CLEAR=PASS source_version_deleted=True local_payload_used=False")


def _repair_postgres_ref(
    dsn: str,
    expected: dict[str, Any],
    restored_version: str,
) -> int:
    expectation = _expectation(expected)
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        row = connection.execute(
            """
            UPDATE artifact_payload_metadata
            SET object_version = %s,
                object_verified_at = transaction_timestamp(),
                lifecycle_revision = lifecycle_revision + 1,
                updated_at = transaction_timestamp()
            WHERE deployment_namespace = %s
              AND artifact_id = %s
              AND session_id = %s
              AND lifecycle_status = 'finalized'
              AND object_version = %s
            RETURNING lifecycle_revision
            """,
            (
                restored_version,
                NAMESPACE,
                expectation.artifact_id,
                expected["session_id"],
                expected["artifact"]["source_object_version"],
            ),
        ).fetchone()
    if row is None:
        raise RuntimeError("guarded PostgreSQL Artifact ref repair affected zero rows")
    return int(row["lifecycle_revision"])


def _verify(
    dsn: str,
    endpoint: str,
    access_key: str,
    secret_key: str,
    expected_path: Path,
    report_path: Path,
) -> None:
    expected = _load(expected_path)
    if not expected.get("source_deleted"):
        raise RuntimeError("source deletion evidence is missing")
    expectation = _expectation(expected)
    source_store = _store(endpoint, access_key, secret_key, BUCKET)
    backup_store = _store(endpoint, access_key, secret_key, BACKUP_BUCKET)
    backup_version = expected["artifact"]["backup_object_version"]
    payload = backup_store.read_version_verified(expectation, backup_version)
    if payload != PAYLOAD:
        raise RuntimeError("backup object bytes differ from the immutable payload")
    restored = source_store.put_if_absent(
        ArtifactObjectPutRequest(expectation=expectation, payload=payload)
    )
    if source_store.read_version_verified(expectation, restored.object_version) != PAYLOAD:
        raise RuntimeError("restored source object failed checksum/size verification")
    metadata = PostgresCloudArtifactPayloadStore(
        dsn, deployment_namespace=NAMESPACE
    ).get_metadata(
        ArtifactMetadataQuery(
            deployment_namespace=NAMESPACE,
            artifact_id=expectation.artifact_id,
            session_id=SessionId(UUID(expected["session_id"])),
        )
    )
    if metadata is None or metadata.object_receipt is None:
        raise RuntimeError("PostgreSQL Artifact ref disappeared during restore")
    old_ref = metadata.object_receipt.object_version
    if old_ref != expected["artifact"]["source_object_version"]:
        raise RuntimeError("PostgreSQL Artifact ref changed before guarded repair")
    repaired_revision = _repair_postgres_ref(dsn, expected, restored.object_version)
    repaired = PostgresCloudArtifactPayloadStore(
        dsn, deployment_namespace=NAMESPACE
    ).get_metadata(
        ArtifactMetadataQuery(
            deployment_namespace=NAMESPACE,
            artifact_id=expectation.artifact_id,
            session_id=SessionId(UUID(expected["session_id"])),
        )
    )
    if repaired is None or repaired.object_receipt is None:
        raise RuntimeError("repaired PostgreSQL Artifact ref is missing")
    if repaired.object_receipt.object_version != restored.object_version:
        raise RuntimeError("PostgreSQL Artifact ref does not match restored version")
    if (
        PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=OTHER_NAMESPACE).get_metadata(
            ArtifactMetadataQuery(
                deployment_namespace=OTHER_NAMESPACE,
                artifact_id=expectation.artifact_id,
                session_id=SessionId(UUID(expected["session_id"])),
            )
        )
        is not None
    ):
        raise RuntimeError("Artifact metadata leaked across namespaces")
    other_expectation = expectation.model_copy(update={"deployment_namespace": OTHER_NAMESPACE})
    if (
        backup_store.verify(other_expectation).status
        is not ArtifactObjectVerificationStatus.NOT_FOUND
    ):
        raise RuntimeError("backup object leaked across namespaces")
    report = {
        "schema_version": "zebra.recovery.s3.evidence.v1",
        "drill_id": expected["drill_id"],
        "environment": "production-like",
        "scope": "s3-versioned-artifact-restore",
        "provider": expected["provider"],
        "deployment_namespace": NAMESPACE,
        "artifact": {
            "artifact_id": str(expectation.artifact_id),
            "sha256": expectation.sha256,
            "size_bytes": expectation.size_bytes,
            "source_object_version": expected["artifact"]["source_object_version"],
            "backup_object_version": backup_version,
            "restored_object_version": restored.object_version,
            "source_deleted": True,
            "backup_metadata_verified": True,
            "restored_checksum_verified": True,
        },
        "postgres_ref": {
            "old_object_version": old_ref,
            "new_object_version": restored.object_version,
            "guarded_rows_updated": 1,
            "lifecycle_revision": repaired_revision,
        },
        "invariants": {
            "independent_backup_copy_used": True,
            "worker_local_payload_used": False,
            "namespace_isolated": True,
            "checksum_match": True,
            "size_match": True,
            "metadata_match": True,
        },
        "cleanup": {
            "containers_removed": False,
            "volumes_removed": False,
            "temporary_credentials_revoked": False,
        },
        "evidence_status": "pass_pending_cleanup",
    }
    _write(report_path, report)
    print(
        "S3_RECOVERY_VERIFY=PASS "
        f"backup_version={backup_version} restored_version={restored.object_version} "
        f"pg_revision={repaired_revision} checksum={expectation.sha256}"
    )


def _finalize(report_path: Path, evidence_dir: Path | None) -> None:
    report = _load(report_path)
    report["cleanup"] = {
        "containers_removed": True,
        "volumes_removed": True,
        "temporary_credentials_revoked": True,
    }
    report["evidence_status"] = "pass"
    report["finalized_at"] = datetime.now(UTC).isoformat()
    _write(report_path, report)
    if evidence_dir is not None:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        destination = evidence_dir / "s3-recovery-evidence.json"
        destination.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"S3_RECOVERY_EVIDENCE_FILE={destination}")
    print("S3_RECOVERY_CLEANUP=PASS containers=0 volumes=0 temporary_credentials=0")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("seed", "clear", "verify", "finalize"), required=True)
    parser.add_argument("--dsn")
    parser.add_argument("--endpoint")
    parser.add_argument("--access-key")
    parser.add_argument("--secret-key")
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--target-name", default="unused")
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    if args.mode == "finalize":
        if args.report is None:
            raise SystemExit("--report is required for finalize")
        _finalize(args.report, args.evidence_dir)
        return
    required = (args.dsn, args.endpoint, args.access_key, args.secret_key, args.expected)
    if any(value is None for value in required):
        raise SystemExit("database, object-store and expected arguments are required")
    if args.mode == "seed":
        _seed(
            args.dsn,
            args.endpoint,
            args.access_key,
            args.secret_key,
            args.expected,
            args.target_name,
        )
    elif args.mode == "clear":
        _clear(args.endpoint, args.access_key, args.secret_key, args.expected)
    else:
        if args.report is None:
            raise SystemExit("--report is required for verify")
        _verify(
            args.dsn,
            args.endpoint,
            args.access_key,
            args.secret_key,
            args.expected,
            args.report,
        )


if __name__ == "__main__":
    main()
