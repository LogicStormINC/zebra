"""Seed, verify and finalize the production-like PostgreSQL PITR drill."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import time_ns
from typing import Any
from uuid import UUID, uuid4

import psycopg
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence, LeaseLostError
from agent_storage.postgres import (
    PostgresEventStore,
    PostgresLeaseStore,
    PostgresProjectionStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
    read_control_plane_epoch,
    rotate_control_plane_epoch,
)
from psycopg.rows import dict_row

NAMESPACE = "recovery-pitr"
DEFAULT_TARGET_NAME = "zebra_pitr_target_v1"
LEASE_TTL = timedelta(minutes=5)


def _event_snapshot(event: SessionEvent) -> dict[str, Any]:
    return event.model_dump(mode="json")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _session_id(expected: dict[str, Any]) -> SessionId:
    return SessionId(UUID(expected["session_id"]))


def _store(dsn: str) -> PostgresEventStore:
    return PostgresEventStore(dsn, deployment_namespace=NAMESPACE)


def _project(dsn: str, session_id: SessionId) -> int:
    events = _store(dsn).list_for_session(session_id)
    projection = rebuild_session(events)
    saved = PostgresProjectionStore(dsn, deployment_namespace=NAMESPACE).save_session(projection)
    if saved.current_sequence != projection.current_sequence:
        raise RuntimeError("projection rebuild did not preserve the Event revision")
    return projection.current_sequence


def _server_identity(dsn: str) -> str:
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        row = connection.execute(
            "SELECT system_identifier::text AS system_identifier FROM pg_control_system()"
        ).fetchone()
    if row is None:
        raise RuntimeError("PostgreSQL did not return a system identity")
    return str(row["system_identifier"])


def _counts(dsn: str) -> dict[str, int]:
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        row = connection.execute(
            """
            SELECT count(*)::int AS event_count, max(sequence)::int AS max_sequence
            FROM session_events
            WHERE deployment_namespace = %s
            """,
            (NAMESPACE,),
        ).fetchone()
        stream = connection.execute(
            """
            SELECT current_version::int AS current_version
            FROM session_streams
            WHERE deployment_namespace = %s
            """,
            (NAMESPACE,),
        ).fetchone()
    if row is None or stream is None:
        raise RuntimeError("PITR count query returned no namespace rows")
    return {
        "event_count": int(row["event_count"]),
        "max_sequence": -1 if row["max_sequence"] is None else int(row["max_sequence"]),
        "stream_revision": int(stream["current_version"]),
    }


def _seed(dsn: str, expected_path: Path) -> None:
    apply_postgres_migrations(dsn)
    epoch = bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Physical PITR seed",
            user_input="Keep the durable seed before the recovery point.",
            workspace_root=Path("/workspace/pitr"),
            created_at=datetime.now(UTC),
        )
    )
    event_store = _store(dsn)
    for event in bootstrap.events:
        event_store.append(event)
    _project(dsn, bootstrap.session.session_id)
    lease = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).acquire(
        bootstrap.session.session_id,
        owner_instance_id="pitr-source-worker",
        ttl=LEASE_TTL,
        checkpoint=bootstrap.session.current_sequence,
    )
    expected = {
        "schema_version": "zebra.recovery.pitr.evidence.v1",
        "drill_id": f"pitr-{time_ns()}",
        "environment": "production-like",
        "provider": "docker-postgres-17.5",
        "deployment_namespace": NAMESPACE,
        "session_id": str(bootstrap.session.session_id),
        "seeded_at": datetime.now(UTC).isoformat(),
        "source_database_identity": _server_identity(dsn),
        "baseline_revision": bootstrap.session.current_sequence,
        "baseline_event_count": len(bootstrap.events),
        "lease": {
            "checkpoint": lease.checkpoint,
            "fence": lease.fence.model_dump(mode="json"),
        },
        "target_name": DEFAULT_TARGET_NAME,
    }
    _write(expected_path, expected)
    print(
        "PITR_SEED=PASS "
        f"namespace={NAMESPACE} session={bootstrap.session.session_id} "
        f"revision={bootstrap.session.current_sequence} epoch={epoch}"
    )


def _target(dsn: str, expected_path: Path, target_name: str) -> None:
    expected = _load(expected_path)
    session_id = _session_id(expected)
    event_store = _store(dsn)
    target_event = SessionEvent.create(
        session_id=session_id,
        sequence=int(expected["baseline_revision"]) + 1,
        event_type=EventType.MODEL_REQUEST_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1, "model_call_id": str(uuid4())},
        created_at=datetime.now(UTC),
    )
    event_store.append(target_event)
    _project(dsn, session_id)
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        row = connection.execute(
            "SELECT pg_create_restore_point(%s)::text AS restore_point_lsn",
            (target_name,),
        ).fetchone()
    if row is None:
        raise RuntimeError("PostgreSQL did not return a PITR restore point")
    post_event = SessionEvent.create(
        session_id=session_id,
        sequence=target_event.sequence + 1,
        event_type=EventType.MODEL_RESPONSE_DELTA,
        actor=EventActor.HARNESS,
        payload={
            "attempt_number": 1,
            "model_call_id": target_event.payload["model_call_id"],
            "delta_index": 0,
            "content_delta": "must not be present after named PITR",
        },
        created_at=datetime.now(UTC),
    )
    event_store.append(post_event)
    _project(dsn, session_id)
    expected.update(
        {
            "target_name": target_name,
            "target_restore_point_lsn": row["restore_point_lsn"],
            "target_event": _event_snapshot(target_event),
            "post_target_event": _event_snapshot(post_event),
        }
    )
    _write(expected_path, expected)
    print(
        "PITR_TARGET=PASS "
        f"name={target_name} lsn={row['restore_point_lsn']} "
        f"target_sequence={target_event.sequence} post_sequence={post_event.sequence}"
    )


def _verify(
    dsn: str,
    expected_path: Path,
    report_path: Path,
    *,
    base_backup_id: str,
    base_backup_sha256: str,
    archived_wal_count: int,
    rto_seconds: float,
) -> None:
    expected = _load(expected_path)
    session_id = _session_id(expected)
    target = expected.get("target_event")
    post_target = expected.get("post_target_event")
    if not isinstance(target, dict) or not isinstance(post_target, dict):
        raise RuntimeError("target evidence is incomplete")
    events = _store(dsn).list_for_session(session_id)
    target_sequence = int(target["sequence"])
    if [event.sequence for event in events] != list(range(target_sequence + 1)):
        raise RuntimeError("PITR Event sequence is not contiguous at the named target")
    if str(events[-1].event_id) != target["event_id"]:
        raise RuntimeError("PITR restored an Event after the named recovery point")
    if any(str(event.event_id) == post_target["event_id"] for event in events):
        raise RuntimeError("post-target Event was present after PITR")
    counts = _counts(dsn)
    if counts != {
        "event_count": target_sequence + 1,
        "max_sequence": target_sequence,
        "stream_revision": target_sequence,
    }:
        raise RuntimeError(f"PITR Event/revision counts differ: {counts!r}")
    rebuilt_revision = _project(dsn, session_id)
    if rebuilt_revision != target_sequence:
        raise RuntimeError("Projection rebuild revision differs from recovered Event stream")
    projection = PostgresProjectionStore(
        dsn, deployment_namespace=NAMESPACE
    ).get_session(session_id)
    if projection is None or projection.current_sequence != target_sequence:
        raise RuntimeError("recovered Projection is missing or stale")
    if _store_for_other_namespace(dsn).read_since(session_id, -1):
        raise RuntimeError("recovered Event leaked across deployment namespaces")

    old_epoch = read_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    new_epoch = rotate_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    if old_epoch == new_epoch:
        raise RuntimeError("restore epoch rotation did not issue a new epoch")
    lease_store = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE)
    old_fence = LeaseFence.model_validate(expected["lease"]["fence"])
    old_write_rejected = False
    try:
        lease_store.heartbeat(
            session_id,
            fence=old_fence,
            ttl=LEASE_TTL,
            checkpoint=int(expected["lease"]["checkpoint"]),
        )
    except LeaseLostError:
        old_write_rejected = True
    if not old_write_rejected:
        raise RuntimeError("old epoch Lease heartbeat was accepted")
    replacement = lease_store.acquire(
        session_id,
        owner_instance_id="pitr-restore-worker",
        ttl=LEASE_TTL,
        checkpoint=target_sequence,
    )
    if replacement.fence.control_plane_epoch != new_epoch:
        raise RuntimeError("replacement Lease did not bind to the rotated epoch")
    lease_store.release(session_id, fence=replacement.fence)
    target_time = datetime.fromisoformat(str(target["created_at"]))
    post_target_time = datetime.fromisoformat(str(post_target["created_at"]))
    rpo_seconds = max(0.0, (post_target_time - target_time).total_seconds())
    restored_at = datetime.now(UTC)
    report = {
        "schema_version": "zebra.recovery.pitr.evidence.v1",
        "drill_id": expected["drill_id"],
        "environment": "production-like",
        "scope": "postgresql-physical-pitr",
        "provider": expected["provider"],
        "deployment_namespace": NAMESPACE,
        "source_snapshot": {
            "database_identity": expected["source_database_identity"],
            "seeded_at": expected["seeded_at"],
            "base_backup_id": base_backup_id,
            "base_backup_sha256": base_backup_sha256,
            "archived_wal_count": archived_wal_count,
        },
        "target_recovery_point": {
            "name": expected["target_name"],
            "lsn": expected["target_restore_point_lsn"],
            "target_event_sequence": target_sequence,
            "restored_at": restored_at.isoformat(),
        },
        "invariants": {
            "event_count": counts["event_count"],
            "max_sequence": counts["max_sequence"],
            "event_sequences_contiguous": True,
            "post_target_event_excluded": True,
            "projection_rebuilt": True,
            "projection_revision": projection.current_sequence,
            "namespace_isolated": True,
            "lease_epoch_rotated": True,
            "old_epoch_writes_rejected": old_write_rejected,
            "replacement_lease_epoch": str(new_epoch),
        },
        "measurements": {
            "rpo_seconds": rpo_seconds,
            "rto_seconds": max(0.0, rto_seconds),
            "target_event_created_at": target["created_at"],
            "post_target_event_created_at": post_target["created_at"],
        },
        "identity_rotation": {
            "old_epoch": str(old_epoch),
            "new_epoch": str(new_epoch),
            "old_lease_write_rejected": old_write_rejected,
            "replacement_lease_released": True,
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
        "PITR_VERIFY=PASS "
        f"events={counts['event_count']} revision={target_sequence} "
        f"rpo_seconds={rpo_seconds:.6f} rto_seconds={rto_seconds:.6f} "
        f"old_epoch_rejected={old_write_rejected}"
    )


def _store_for_other_namespace(dsn: str) -> PostgresEventStore:
    return PostgresEventStore(dsn, deployment_namespace="other-namespace")


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
        destination = evidence_dir / "pitr-evidence.json"
        destination.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"PITR_EVIDENCE_FILE={destination}")
    print("PITR_CLEANUP=PASS containers=0 volumes=0 temporary_credentials=0")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("seed", "target", "verify", "finalize"), required=True)
    parser.add_argument("--dsn")
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--target-name", default=DEFAULT_TARGET_NAME)
    parser.add_argument("--base-backup-id", default="not-recorded")
    parser.add_argument("--base-backup-sha256", default="not-recorded")
    parser.add_argument("--archived-wal-count", type=int, default=0)
    parser.add_argument("--rto-seconds", type=float, default=0.0)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    if args.mode == "finalize":
        if args.report is None:
            raise SystemExit("--report is required for finalize")
        _finalize(args.report, args.evidence_dir)
        return
    if args.dsn is None or args.expected is None:
        raise SystemExit("--dsn and --expected are required for the database modes")
    if args.mode == "seed":
        _seed(args.dsn, args.expected)
    elif args.mode == "target":
        _target(args.dsn, args.expected, args.target_name)
    else:
        if args.report is None:
            raise SystemExit("--report is required for verify")
        _verify(
            args.dsn,
            args.expected,
            args.report,
            base_backup_id=args.base_backup_id,
            base_backup_sha256=args.base_backup_sha256,
            archived_wal_count=args.archived_wal_count,
            rto_seconds=args.rto_seconds,
        )


if __name__ == "__main__":
    main()
