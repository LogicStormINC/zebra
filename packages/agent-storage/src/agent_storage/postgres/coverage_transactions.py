"""Coverage Event queries and the Session→lease→Task→run→stream boundary."""

from datetime import datetime
from typing import Any

from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.coverage_persistence import CoverageRunBinding, canonical_coverage_bytes
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.leases import LeaseFence
from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest
from agent_core.ports.coverage import CoverageCommit

from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.leases import assert_current_lease_fence, lock_session_lease_boundary
from agent_storage.postgres.task_index_transactions import _lock_task

COVERAGE_TYPES = (
    EventType.COVERAGE_MANIFEST_COMMITTED.value,
    EventType.COVERAGE_BATCH_ACCEPTED.value,
    EventType.COVERAGE_RUN_CANCELLED.value,
)


def run_events(connection: Any, deployment: str, namespace: str, run_id: str) -> list[Any]:
    return list(connection.execute(
        """SELECT * FROM session_events WHERE deployment_namespace=%s
           AND payload->>'namespace'=%s AND payload->>'run_id'=%s
           AND event_type = ANY(%s) ORDER BY sequence""",
        (deployment, namespace, run_id, list(COVERAGE_TYPES)),
    ).fetchall())


def manifest_event(connection: Any, deployment: str, namespace: str, run_id: str) -> Any:
    rows = connection.execute(
        """SELECT * FROM session_events WHERE deployment_namespace=%s
           AND payload->>'namespace'=%s AND payload->>'run_id'=%s
           AND event_type='coverage_manifest_committed' LIMIT 2""",
        (deployment, namespace, run_id),
    ).fetchall()
    if len(rows) > 1:
        raise ValueError("coverage run has conflicting source manifests")
    return rows[0] if rows else None


def binding_from_event(row: Any, namespace: str, run_id: str) -> CoverageRunBinding:
    validate_event_fence(row["payload"])
    binding = CoverageRunBinding.model_validate(row["payload"]["binding"])
    if (
        binding.namespace != namespace or binding.run_id != run_id
        or binding.session_id != row["session_id"]
        or row["payload"]["namespace"] != namespace or row["payload"]["run_id"] != run_id
    ):
        raise ValueError("coverage manifest Event binding conflicts")
    return binding


def validate_event_fence(payload: dict[str, Any]) -> None:
    """Replay validates historical evidence, not the historical lease's liveness."""
    descriptor = payload.get("fence")
    fence = LeaseFence.model_validate(descriptor)
    if (
        descriptor != fence.model_dump(mode="json")
        or type(descriptor["fencing_token"]) is not int
    ):
        raise ValueError("coverage Event requires a canonical full lease fence")


def lock_run(
    connection: Any, deployment: str, binding: CoverageRunBinding, fence: LeaseFence | None,
    *, cancelling: bool = False,
) -> tuple[Any, int]:
    lock_session_lease_boundary(connection, deployment, binding.session_id)
    if fence is not None:
        assert_current_lease_fence(connection, deployment, binding.session_id, fence)
    _lock_task(connection, deployment, binding.task_id)
    task = connection.execute(
        """SELECT active_segment_id FROM agent_tasks
           WHERE deployment_namespace=%s AND task_id=%s FOR UPDATE""",
        (deployment, binding.task_id),
    ).fetchone()
    if task is None:
        raise ValueError("coverage Task binding is missing")
    if fence is not None and task["active_segment_id"] != binding.session_id:
        raise ValueError("coverage Session is not the active Task segment")
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 78))",
        (canonical_coverage_bytes([deployment, binding.namespace, binding.run_id]).decode(),),
    )
    row = connection.execute(
        """SELECT * FROM coverage_runs WHERE deployment_namespace=%s
           AND namespace=%s AND run_id=%s FOR UPDATE""",
        (deployment, binding.namespace, binding.run_id),
    ).fetchone()
    stream = connection.execute(
        """SELECT current_version FROM session_streams WHERE deployment_namespace=%s
           AND session_id=%s FOR UPDATE""",
        (deployment, binding.session_id),
    ).fetchone()
    if stream is None:
        raise ValueError("coverage Session stream is missing")
    if fence is not None:
        validate_write(connection, deployment, binding, fence, cancelling=cancelling)
    return row, int(stream["current_version"])


def validate_write(
    connection: Any, deployment: str, binding: CoverageRunBinding, fence: LeaseFence,
    *, cancelling: bool = False,
) -> tuple[datetime, str, int]:
    assert_current_lease_fence(connection, deployment, binding.session_id, fence)
    now: datetime = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    if not cancelling and not binding.snapshot.as_of <= now < binding.snapshot.expires_at:
        raise ValueError("coverage snapshot has expired or is not yet valid")
    authority = connection.execute(
        """SELECT binding.snapshot_json, binding.binding_digest, session.namespace_id
           FROM execution_segments segment
           JOIN session_projections session
             ON session.deployment_namespace=segment.deployment_namespace
             AND session.session_id=segment.session_id
           JOIN LATERAL (SELECT snapshot_json, binding_digest FROM task_binding_snapshots
             WHERE deployment_namespace=segment.deployment_namespace AND task_id=segment.task_id
             ORDER BY binding_revision DESC LIMIT 1) binding ON TRUE
           WHERE segment.deployment_namespace=%s AND segment.session_id=%s
             AND segment.task_id=%s""",
        (deployment, binding.session_id, binding.task_id),
    ).fetchone()
    if authority is None:
        raise ValueError("coverage requires persisted cloud Host authority")
    task_binding = TaskBindingSnapshot.model_validate(authority["snapshot_json"])
    host = task_binding.host_capability
    context = host.host_context
    if (
        task_binding.task_id != str(binding.task_id)
        or task_binding.binding_digest != authority["binding_digest"]
        or host.namespace_id != binding.snapshot.namespace
        or host.host_app_id != binding.snapshot.host_id
        or context is None or host.grant_digest != host_context_digest(context)
        or context.namespace_id != host.namespace_id or context.host_app_id != host.host_app_id
        or authority["namespace_id"] != host.namespace_id
        or (not cancelling and (host.grant_expires_at is None or host.grant_expires_at <= now))
        or (not cancelling and (context.expires_at is None or context.expires_at <= now))
        or host.bound_at > now or task_binding.bound_at > now
    ):
        raise ValueError("coverage Host binding is invalid, mismatched or expired")
    # snapshot.authority_revision is an opaque external permission revision, not
    # a grant ID. Storage pins the independently persisted Task binding instead.
    source = manifest_event(connection, deployment, binding.namespace, binding.run_id)
    if not cancelling and source is not None and (
        source["payload"].get("task_binding_digest") != task_binding.binding_digest
        or source["payload"].get("task_binding_revision") != task_binding.binding_revision
    ):
        raise ValueError("coverage persisted Task binding changed after manifest commit")
    if cancelling:
        return now, task_binding.binding_digest, task_binding.binding_revision
    # v1 does not reactivate coverage in a stopped Session. A future continuation
    # contract must bind a fresh execution boundary before enabling same-Session resume.
    stopped = connection.execute(
        """SELECT 1 FROM session_events WHERE deployment_namespace=%s AND session_id=%s
           AND (event_type IN ('session_cancelled','session_failed','session_completed')
             OR (event_type='session_command_accepted' AND payload->>'kind' IN ('stop','cancel')))
           LIMIT 1""",
        (deployment, binding.session_id),
    ).fetchone()
    if stopped is not None:
        raise ValueError("coverage Session is terminal or has accepted STOP/cancel")
    return now, task_binding.binding_digest, task_binding.binding_revision


def assert_projection(
    connection: Any, deployment: str, binding: CoverageRunBinding, row: Any,
) -> None:
    manifest = manifest_event(connection, deployment, binding.namespace, binding.run_id)
    latest = connection.execute(
        """SELECT sequence, session_id, event_type FROM session_events
           WHERE deployment_namespace=%s AND payload->>'namespace'=%s AND payload->>'run_id'=%s
           AND event_type=ANY(%s) ORDER BY sequence DESC LIMIT 1""",
        (deployment, binding.namespace, binding.run_id, list(COVERAGE_TYPES)),
    ).fetchone()
    if (
        row is None or manifest is None or latest is None
        or binding_from_event(manifest, binding.namespace, binding.run_id) != binding
        or CoverageRunBinding.model_validate(row["binding"]) != binding
        or row["session_id"] != binding.session_id or row["task_id"] != binding.task_id
        or latest["session_id"] != binding.session_id
        or row["source_watermark"] != latest["sequence"]
        or row["cancelled"] != (latest["event_type"] == EventType.COVERAGE_RUN_CANCELLED.value)
    ):
        raise ValueError("coverage projection disagrees with source Events; rebuild required")


def validate_request(binding: CoverageRunBinding, request: CoverageCommit) -> None:
    if (
        request.namespace != binding.namespace or request.run_id != binding.run_id
        or request.session_id != binding.session_id or request.task_id != binding.task_id
        or request.snapshot_id != binding.snapshot.snapshot_id
        or request.contract_digest != binding.contract.digest
        or request.manifest_digest != binding.snapshot.manifest_digest
    ):
        raise ValueError("coverage batch binding conflicts with manifest")


def append_coverage_event(
    connection: Any, deployment: str, binding: CoverageRunBinding, fence: LeaseFence,
    sequence: int, event_type: EventType, payload: dict[str, Any],
) -> SessionEvent:
    now, task_digest, task_revision = validate_write(
        connection, deployment, binding, fence,
        cancelling=event_type == EventType.COVERAGE_RUN_CANCELLED,
    )
    payload = {"namespace": binding.namespace, "run_id": binding.run_id,
               **payload, "fence": fence.model_dump(mode="json")}
    if event_type == EventType.COVERAGE_MANIFEST_COMMITTED:
        payload.update(task_binding_digest=task_digest, task_binding_revision=task_revision)
    if len(canonical_coverage_bytes(payload)) > 64 * 1024:
        raise ValueError("coverage Event descriptor exceeds the bounded payload limit")
    event = SessionEvent.create(
        session_id=binding.session_id, sequence=sequence, event_type=event_type,
        actor=EventActor.SYSTEM, payload=payload, created_at=now,
    )
    return append_event_in_transaction(connection, deployment, event)


def request_digest(request: CoverageCommit) -> str:
    # The canonical Artifact digest binds all results independent of tuple order;
    # every other request field (including Artifact identity) is bound explicitly.
    return coverage_digest(request.model_dump(mode="json", exclude={"results"}))
