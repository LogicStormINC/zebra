"""Coverage Event queries and the Session→lease→Task→run→stream boundary."""

import re
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.coverage_persistence import CoverageRunBinding, canonical_coverage_bytes
from agent_core.domain.coverage_task_admission import coverage_admission_input
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.leases import LeaseFence
from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest
from agent_core.ports.coverage import CoverageCommit

from agent_storage.postgres.coverage_write_authority import read_write_authority
from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.leases import assert_current_lease_fence, lock_session_lease_boundary
from agent_storage.postgres.task_index_transactions import _lock_task

COVERAGE_TYPES = (
    EventType.COVERAGE_MANIFEST_COMMITTED.value,
    EventType.COVERAGE_BATCH_ACCEPTED.value,
    EventType.COVERAGE_RUN_CANCELLED.value,
    EventType.COVERAGE_REPORT_CERTIFIED.value,
    EventType.COVERAGE_MODEL_BUDGET_INITIALIZED.value,
    EventType.COVERAGE_MODEL_CALL_RESERVED.value,
    EventType.COVERAGE_MODEL_USAGE_RECORDED.value,
)


def validated_binding(binding: CoverageRunBinding) -> CoverageRunBinding:
    """Validate every raw nested field before equality, serialization or lock I/O."""
    return CoverageRunBinding.model_validate(coverage_admission_input(binding))


def assert_not_certified(connection: Any, deployment: str, binding: CoverageRunBinding) -> None:
    row = connection.execute(
        """SELECT 1 FROM session_events WHERE deployment_namespace=%s AND session_id=%s
           AND event_type='coverage_report_certified' AND payload->>'namespace'=%s
           AND payload->>'run_id'=%s LIMIT 1""",
        (deployment, binding.session_id, binding.namespace, binding.run_id),
    ).fetchone()
    if row is not None:
        raise ValueError("certified coverage is immutable")


def run_events(connection: Any, deployment: str, namespace: str, run_id: str) -> list[Any]:
    return list(
        connection.execute(
            """SELECT * FROM session_events WHERE deployment_namespace=%s
           AND payload->>'namespace'=%s AND payload->>'run_id'=%s
           AND event_type = ANY(%s) ORDER BY sequence""",
            (deployment, namespace, run_id, list(COVERAGE_TYPES)),
        ).fetchall()
    )


def iter_run_events(
    connection: Any, deployment: str, namespace: str, run_id: str, *, locked: bool = False
) -> Iterator[Any]:
    """Full source rows, keyset bounded without skipping equal sequences across Sessions."""
    upper = connection.execute(
        """SELECT max(sequence) AS last FROM session_events WHERE deployment_namespace=%s
           AND payload->>'namespace'=%s AND payload->>'run_id'=%s AND event_type=ANY(%s)""",
        (deployment, namespace, run_id, list(COVERAGE_TYPES)),
    ).fetchone()["last"]
    if upper is None:
        return
    cursor: tuple[Any, Any] = (-1, None)
    while True:
        rows = connection.execute(
            """SELECT * FROM session_events WHERE deployment_namespace=%s
               AND payload->>'namespace'=%s AND payload->>'run_id'=%s
               AND event_type=ANY(%s) AND sequence<=%s AND (sequence,event_id)>(%s,%s::uuid)
               ORDER BY sequence,event_id LIMIT 100""" + (" FOR SHARE" if locked else ""),
            (deployment, namespace, run_id, list(COVERAGE_TYPES), upper, *cursor),
        ).fetchall()
        if not rows:
            return
        yield from rows
        cursor = rows[-1]["sequence"], rows[-1]["event_id"]


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
        binding.namespace != namespace
        or binding.run_id != run_id
        or binding.session_id != row["session_id"]
        or row["payload"]["namespace"] != namespace
        or row["payload"]["run_id"] != run_id
    ):
        raise ValueError("coverage manifest Event binding conflicts")
    return binding


def validate_event_fence(payload: dict[str, Any]) -> None:
    """Replay validates historical evidence, not the historical lease's liveness."""
    descriptor = payload.get("fence")
    fence = LeaseFence.model_validate(descriptor)
    if descriptor != fence.model_dump(mode="json") or type(descriptor["fencing_token"]) is not int:
        raise ValueError("coverage Event requires a canonical full lease fence")


def lock_run(
    connection: Any,
    deployment: str,
    binding: CoverageRunBinding,
    fence: LeaseFence | None,
    *,
    cancelling: bool = False,
    expected_stream_revision: int | None = None,
    task_binding_digest: str | None = None,
) -> tuple[Any, int]:
    if (expected_stream_revision is None) != (task_binding_digest is None):
        raise ValueError(
            "coverage bind guards require both stream revision and Task binding digest"
        )
    if expected_stream_revision is not None and (
        type(expected_stream_revision) is not int or expected_stream_revision < 0
    ):
        raise ValueError("coverage expected stream revision must be a nonnegative integer")
    if task_binding_digest is not None and (
        not isinstance(task_binding_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", task_binding_digest) is None
        or fence is None
    ):
        raise ValueError("coverage expected Task binding digest requires canonical hash and fence")
    binding = validated_binding(binding)
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
    if (
        expected_stream_revision is not None
        and stream["current_version"] != expected_stream_revision
    ):
        raise ValueError("coverage stream revision changed before bind")
    if fence is not None:
        _, task_digest, _ = validate_write(
            connection,
            deployment,
            binding,
            fence,
            cancelling=cancelling,
        )
        if task_binding_digest is not None and task_digest != task_binding_digest:
            raise ValueError("coverage Task binding changed before bind")
    return row, int(stream["current_version"])


def validate_write(
    connection: Any,
    deployment: str,
    binding: CoverageRunBinding,
    fence: LeaseFence,
    *,
    cancelling: bool = False,
) -> tuple[datetime, str, int]:
    binding = validated_binding(binding)
    facts = read_write_authority(connection, deployment, binding, fence)
    now: datetime = facts["now"]
    if not cancelling and not binding.snapshot.as_of <= now < binding.snapshot.expires_at:
        raise ValueError("coverage snapshot has expired or is not yet valid")
    authority = facts["authority"]
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
        or context is None
        or host.grant_digest != host_context_digest(context)
        or context.namespace_id != host.namespace_id
        or context.host_app_id != host.host_app_id
        or authority["namespace_id"] != host.namespace_id
        or (not cancelling and (host.grant_expires_at is None or host.grant_expires_at <= now))
        or (not cancelling and (context.expires_at is None or context.expires_at <= now))
        or host.bound_at > now
        or task_binding.bound_at > now
    ):
        raise ValueError("coverage Host binding is invalid, mismatched or expired")
    # snapshot.authority_revision is an opaque external permission revision, not
    # a grant ID. Storage pins the independently persisted Task binding instead.
    source = facts["manifests"][0] if facts["manifests"] else None
    if (
        not cancelling
        and source is not None
        and (
            source["payload"].get("task_binding_digest") != task_binding.binding_digest
            or source["payload"].get("task_binding_revision") != task_binding.binding_revision
        )
    ):
        raise ValueError("coverage persisted Task binding changed after manifest commit")
    if cancelling:
        return now, task_binding.binding_digest, task_binding.binding_revision
    # v1 does not reactivate coverage in a stopped Session. A future continuation
    # contract must bind a fresh execution boundary before enabling same-Session resume.
    if facts["stopped"]:
        raise ValueError("coverage Session is terminal or has accepted STOP/cancel")
    return now, task_binding.binding_digest, task_binding.binding_revision


def assert_projection(
    connection: Any,
    deployment: str,
    binding: CoverageRunBinding,
    row: Any,
) -> None:
    binding = validated_binding(binding)
    manifest = manifest_event(connection, deployment, binding.namespace, binding.run_id)
    latest = connection.execute(
        """SELECT sequence, session_id, event_type FROM session_events
           WHERE deployment_namespace=%s AND payload->>'namespace'=%s AND payload->>'run_id'=%s
           AND event_type=ANY(%s) ORDER BY sequence DESC LIMIT 1""",
        (deployment, binding.namespace, binding.run_id, list(COVERAGE_TYPES)),
    ).fetchone()
    if (
        row is None
        or manifest is None
        or latest is None
        or binding_from_event(manifest, binding.namespace, binding.run_id) != binding
        or CoverageRunBinding.model_validate(row["binding"]) != binding
        or row["session_id"] != binding.session_id
        or row["task_id"] != binding.task_id
        or latest["session_id"] != binding.session_id
        or row["source_watermark"] != latest["sequence"]
        or row["cancelled"] != (latest["event_type"] == EventType.COVERAGE_RUN_CANCELLED.value)
    ):
        raise ValueError("coverage projection disagrees with source Events; rebuild required")


def validate_request(binding: CoverageRunBinding, request: CoverageCommit) -> None:
    if (
        request.namespace != binding.namespace
        or request.run_id != binding.run_id
        or request.session_id != binding.session_id
        or request.task_id != binding.task_id
        or request.snapshot_id != binding.snapshot.snapshot_id
        or request.contract_digest != binding.contract.digest
        or request.manifest_digest != binding.snapshot.manifest_digest
    ):
        raise ValueError("coverage batch binding conflicts with manifest")


def append_coverage_event(
    connection: Any,
    deployment: str,
    binding: CoverageRunBinding,
    fence: LeaseFence,
    sequence: int,
    event_type: EventType,
    payload: dict[str, Any],
) -> SessionEvent:
    now, task_digest, task_revision = validate_write(
        connection,
        deployment,
        binding,
        fence,
        cancelling=event_type == EventType.COVERAGE_RUN_CANCELLED,
    )
    payload = {
        "namespace": binding.namespace,
        "run_id": binding.run_id,
        **payload,
        "fence": fence.model_dump(mode="json"),
    }
    if event_type == EventType.COVERAGE_MANIFEST_COMMITTED:
        payload.update(task_binding_digest=task_digest, task_binding_revision=task_revision)
    if (event_type == EventType.COVERAGE_BATCH_ACCEPTED
            and len(canonical_coverage_bytes(payload)) > 64 * 1024):
        # Optional routing must never make a previously legal descriptor fail.
        payload.pop("record_ids", None)
    if len(canonical_coverage_bytes(payload)) > 64 * 1024:
        raise ValueError("coverage Event descriptor exceeds the bounded payload limit")
    event = SessionEvent.create(
        session_id=binding.session_id,
        sequence=sequence,
        event_type=event_type,
        actor=EventActor.SYSTEM,
        payload=payload,
        created_at=now,
    )
    return append_event_in_transaction(connection, deployment, event)


def request_digest(request: CoverageCommit) -> str:
    # The canonical Artifact digest binds all results independent of tuple order;
    # every other request field (including Artifact identity) is bound explicitly.
    return coverage_digest(request.model_dump(mode="json", exclude={"results"}))
