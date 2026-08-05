"""Seed, clear and verify a fresh-instance recovery composition."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
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
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_artifact_id, new_session_id
from agent_integrations.redis_live_fanout import RedisLiveEventFanout
from agent_storage import (
    PostgresEventStore,
    PostgresLeaseStore,
    S3ArtifactObjectStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
    read_control_plane_epoch,
    rotate_control_plane_epoch,
)
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.session import Session  # type: ignore[import-untyped]
from psycopg.rows import dict_row
from redis import Redis

NAMESPACE = "recovery-restore"
BUCKET = "zebra-artifacts"
SEED_CREATED_AT = datetime(2026, 8, 5, tzinfo=UTC)
ARTIFACT_PAYLOAD = b"zebra recovery restore artifact v1\n"


def _schema_snapshot(connection: psycopg.Connection[Any]) -> dict[str, Any]:
    migration_rows = connection.execute(
        """
        SELECT version, name, checksum
        FROM zebra_schema_migrations
        ORDER BY version
        """
    ).fetchall()
    schema_tables = connection.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    ).fetchall()
    counts: dict[str, int] = {}
    for table_name in (
        "session_streams",
        "session_events",
        "control_plane_epochs",
        "worker_leases",
    ):
        row = connection.execute(
            f"""
            SELECT count(*) AS count
            FROM {table_name}
            WHERE deployment_namespace = %s
            """,
            (NAMESPACE,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"count query returned no row for {table_name}")
        counts[table_name] = int(row["count"])
    return {
        "migration_rows": [
            {
                "version": int(row["version"]),
                "name": row["name"],
                "checksum": row["checksum"],
            }
            for row in migration_rows
        ],
        "schema_tables": [row["table_name"] for row in schema_tables],
        "counts": counts,
    }


def _event_snapshot(event: SessionEvent) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "session_id": str(event.session_id),
        "sequence": event.sequence,
        "event_type": event.event_type.value,
        "payload": event.payload,
        "actor": event.actor.value,
        "created_at": event.created_at.isoformat(),
        "idempotency_key": event.idempotency_key,
    }


def _read_snapshot(dsn: str) -> dict[str, Any]:
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        return _schema_snapshot(connection)


def _object_store(endpoint: str, access_key: str, secret_key: str) -> S3ArtifactObjectStore:
    client = Session().create_client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    return S3ArtifactObjectStore(cast(Any, client), bucket=BUCKET)


def _session_id(expected: dict[str, Any]) -> SessionId:
    return SessionId(UUID(expected["event"]["session_id"]))


def _expectation(expected: dict[str, Any]) -> ArtifactObjectExpectation:
    return ArtifactObjectExpectation.model_validate(expected["artifact"]["expectation"])


def _assert_namespace_event(dsn: str, expected: dict[str, Any]) -> None:
    session_id = _session_id(expected)
    events = PostgresEventStore(dsn, deployment_namespace=NAMESPACE).read_since(session_id, -1)
    if len(events) != 1 or _event_snapshot(events[0]) != expected["event"]:
        raise RuntimeError("restored namespace-scoped Event does not match the seed")
    if PostgresEventStore(dsn, deployment_namespace="other-namespace").read_since(
        session_id, -1
    ):
        raise RuntimeError("restored Event leaked across deployment namespaces")


def _seed(
    dsn: str,
    redis_url: str,
    s3_endpoint: str,
    s3_access_key: str,
    s3_secret_key: str,
    expected_path: Path,
    artifact_path: Path,
) -> None:
    apply_postgres_migrations(dsn)
    epoch = bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    session_id = new_session_id()
    event = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.SYSTEM,
        payload={"title": "fresh instance restore seed"},
        idempotency_key="recovery-restore-seed-1",
        created_at=SEED_CREATED_AT,
    )
    PostgresEventStore(dsn, deployment_namespace=NAMESPACE).append(event)
    lease = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).acquire(
        session_id,
        owner_instance_id="source-worker",
        ttl=timedelta(minutes=10),
    )
    artifact_path.write_bytes(ARTIFACT_PAYLOAD)
    expectation = ArtifactObjectExpectation(
        deployment_namespace=NAMESPACE,
        artifact_id=new_artifact_id(),
        sha256=sha256(ARTIFACT_PAYLOAD).hexdigest(),
        size_bytes=len(ARTIFACT_PAYLOAD),
    )
    receipt = _object_store(s3_endpoint, s3_access_key, s3_secret_key).put_if_absent(
        ArtifactObjectPutRequest(expectation=expectation, payload=ARTIFACT_PAYLOAD)
    )
    RedisLiveEventFanout.from_url(redis_url).publish(
        deployment_namespace=NAMESPACE,
        event=event,
    )
    expected: dict[str, Any] = {
        "epoch": str(epoch),
        "event": _event_snapshot(event),
        "lease": {
            "epoch": str(lease.fence.control_plane_epoch),
            "fencing_token": lease.fence.fencing_token,
            "owner_instance_id": lease.fence.owner_instance_id,
        },
        "artifact": {
            "expectation": expectation.model_dump(mode="json"),
            "object_version": receipt.object_version,
        },
        "schema": _read_snapshot(dsn),
    }
    _assert_namespace_event(dsn, expected)
    expected_path.write_text(
        json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        "RECOVERY_RESTORE_SEED=PASS "
        f"migrations={len(expected['schema']['migration_rows'])} "
        f"events={expected['schema']['counts']['session_events']} "
        f"lease_token={lease.fence.fencing_token}"
    )


def _clear_live_state(
    redis_url: str,
    s3_endpoint: str,
    s3_access_key: str,
    s3_secret_key: str,
    expected_path: Path,
) -> None:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    store = _object_store(s3_endpoint, s3_access_key, s3_secret_key)
    deletion = store.delete_if_version(
        ArtifactObjectDeleteRequest(
            expectation=_expectation(expected),
            object_version=expected["artifact"]["object_version"],
        )
    )
    if deletion.status is not ArtifactObjectDeleteStatus.DELETED:
        raise RuntimeError("source Artifact object was not deleted before restore")
    if (
        store.verify(_expectation(expected)).status
        is not ArtifactObjectVerificationStatus.NOT_FOUND
    ):
        raise RuntimeError("source Artifact object remained observable after clear")
    Redis.from_url(redis_url, decode_responses=True).flushdb()
    print("RECOVERY_RESTORE_CLEAR=PASS artifact=absent redis=flushed")


def _verify(
    dsn: str,
    redis_url: str,
    s3_endpoint: str,
    s3_access_key: str,
    s3_secret_key: str,
    expected_path: Path,
    artifact_path: Path,
) -> None:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    actual_schema = _read_snapshot(dsn)
    if actual_schema != expected["schema"]:
        raise RuntimeError("restored PostgreSQL schema/count snapshot differs from source")
    _assert_namespace_event(dsn, expected)
    session_id = _session_id(expected)
    old_epoch = read_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    if str(old_epoch) != expected["epoch"]:
        raise RuntimeError("restored control-plane epoch differs from source")
    old_lease = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).get(session_id)
    if old_lease is None or str(old_lease.fence.control_plane_epoch) != expected["lease"]["epoch"]:
        raise RuntimeError("restored source lease was not present with its original epoch")

    payload = artifact_path.read_bytes()
    expectation = _expectation(expected)
    receipt = _object_store(s3_endpoint, s3_access_key, s3_secret_key).put_if_absent(
        ArtifactObjectPutRequest(expectation=expectation, payload=payload)
    )
    restored_payload = _object_store(s3_endpoint, s3_access_key, s3_secret_key).read_verified(
        expectation
    )
    if restored_payload != payload:
        raise RuntimeError("restored Artifact bytes failed manifest/checksum verification")

    redis_client = Redis.from_url(redis_url, decode_responses=True)
    redis_client.flushdb()
    fanout = RedisLiveEventFanout.from_url(redis_url)
    barrier = fanout.capture_barrier(deployment_namespace=NAMESPACE, session_id=session_id)
    event = PostgresEventStore(dsn, deployment_namespace=NAMESPACE).read_since(session_id, -1)[0]
    fanout.publish(deployment_namespace=NAMESPACE, event=event)
    batch = fanout.read_after(
        deployment_namespace=NAMESPACE,
        session_id=session_id,
        barrier=barrier,
        durable_sequence=-1,
    )
    if len(batch.events) != 1 or _event_snapshot(batch.events[0].event) != expected["event"]:
        raise RuntimeError("Redis rebuild did not replay the restored Event")

    new_epoch = rotate_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    if new_epoch == old_epoch:
        raise RuntimeError("restore epoch rotation did not issue a fresh authority")
    lease_store = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE)
    if lease_store.get(session_id) is not None:
        raise RuntimeError("stale source lease remained active after epoch rotation")
    new_lease = lease_store.acquire(
        session_id,
        owner_instance_id="restored-worker",
        ttl=timedelta(seconds=30),
    )
    if new_lease.fence.control_plane_epoch != new_epoch or new_lease.fence.fencing_token <= 1:
        raise RuntimeError("restored lease did not receive the new epoch/fencing token")
    lease_store.release(session_id, fence=new_lease.fence)
    print(
        "RECOVERY_RESTORE_VERIFY=PASS "
        f"migrations={len(actual_schema['migration_rows'])} "
        f"events={actual_schema['counts']['session_events']} "
        f"artifact_version={receipt.object_version} "
        f"new_epoch={new_epoch}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("seed", "clear", "verify"), required=True)
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--redis-url", required=True)
    parser.add_argument("--s3-endpoint", required=True)
    parser.add_argument("--s3-access-key", required=True)
    parser.add_argument("--s3-secret-key", required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--artifact-payload", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "seed":
        _seed(
            args.dsn,
            args.redis_url,
            args.s3_endpoint,
            args.s3_access_key,
            args.s3_secret_key,
            args.expected,
            args.artifact_payload,
        )
    elif args.mode == "clear":
        _clear_live_state(
            args.redis_url,
            args.s3_endpoint,
            args.s3_access_key,
            args.s3_secret_key,
            args.expected,
        )
    else:
        _verify(
            args.dsn,
            args.redis_url,
            args.s3_endpoint,
            args.s3_access_key,
            args.s3_secret_key,
            args.expected,
            args.artifact_payload,
        )


if __name__ == "__main__":
    main()
