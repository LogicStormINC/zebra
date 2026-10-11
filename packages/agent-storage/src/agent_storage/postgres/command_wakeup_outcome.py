"""Read-only, scoped command outcomes for a verified AG-UI stream caller."""

from typing import Any
from uuid import UUID

from agent_core.domain.events import SessionEvent
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import TaskId

from agent_storage.postgres.command_wakeup import (
    _scope_from_binding,
    _validated_host_context,
    command_scope_key,
)
from agent_storage.postgres.command_wakeup_receipts import HANDLED_EVENTS
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_replay_headers import read_run_header


class PostgresCommandOutcomeReader:
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    @property
    def deployment_namespace(self) -> str:
        return self._database.deployment_namespace

    def __call__(
        self,
        task_id: TaskId,
        run_id: str,
        accepted_event_id: UUID,
        host_context: HostContextEnvelope,
    ) -> str | None:
        namespace = self.deployment_namespace
        with self._database.connect_task_io() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            try:
                run = read_run_header(connection, namespace, task_id, run_id, None)
            except ValueError as exc:
                raise ValueError("command outcome has no unique canonical run binding") from exc
            if run.anchor is None or run.anchor.event_id != accepted_event_id:
                raise ValueError("command outcome has no unique canonical run binding")
            row = connection.execute(
                """SELECT event_id,session_id,sequence,event_type,actor,created_at,
                   payload->>'command_id' AS command_id
                   FROM session_events WHERE deployment_namespace=%s AND task_id=%s
                   AND task_sequence=%s AND event_id=%s AND session_id=%s AND sequence=%s""",
                (
                    namespace,
                    task_id,
                    run.anchor.task_sequence,
                    accepted_event_id,
                    run.anchor.segment_id,
                    run.anchor.segment_sequence,
                ),
            ).fetchone()
            if row is None:
                raise ValueError("command outcome has no unique canonical run binding")
            command_id = row.pop("command_id")
            if not isinstance(command_id, str) or len(command_id) > 36:
                raise ValueError("canonical command identity is invalid")
            UUID(command_id)
            event = SessionEvent.model_validate({**row, "payload": {"command_id": command_id}})
            bound = _validated_host_context(connection, namespace, event)
            if bound is None or _identity(bound) != _identity(host_context):
                raise ValueError("command outcome Host identity conflicts")
            if not run.control_only and _terminal(connection, namespace, task_id, event, run_id):
                return None
            scope = _scope_from_binding(connection, namespace, event)
            scope_key = command_scope_key(scope)
            pending = connection.execute(
                """SELECT * FROM session_command_pending WHERE deployment_namespace=%s
                AND accepted_event_id=%s AND session_id=%s AND scope_key=%s
                AND tenant_id=%s AND workspace_id=%s AND command_id=%s""",
                (
                    namespace,
                    accepted_event_id,
                    event.session_id,
                    scope_key,
                    scope.tenant_id,
                    scope.workspace_id,
                    event.payload["command_id"],
                ),
            ).fetchone()
            if pending is None:
                return None
            generation = pending["current_generation"]
            receipt = connection.execute(
                """SELECT status, handled_event_id FROM command_handoff_receipts
                WHERE deployment_namespace=%s AND accepted_event_id=%s AND session_id=%s
                AND scope_key=%s AND command_id=%s AND wake_generation=%s""",
                (
                    namespace,
                    accepted_event_id,
                    event.session_id,
                    scope_key,
                    pending["command_id"],
                    generation,
                ),
            ).fetchone()
            if receipt is not None and receipt["handled_event_id"] is not None:
                return None
            if receipt is not None and receipt["status"] == "requires_reconciliation":
                return "command_requires_reconciliation"
            if run.control_only:
                control = connection.execute(
                    """SELECT outcome FROM command_control_receipts WHERE deployment_namespace=%s
                    AND accepted_event_id=%s AND session_id=%s AND scope_key=%s
                    AND command_id=%s AND wake_generation=%s""",
                    (
                        namespace,
                        accepted_event_id,
                        event.session_id,
                        scope_key,
                        pending["command_id"],
                        generation,
                    ),
                ).fetchone()
                if control is not None:
                    if control["outcome"] == "unsupported":
                        return "command_unsupported"
                    if control["outcome"] == "requires_reconciliation":
                        return "command_requires_reconciliation"
            if pending["status"] == "dead":
                return (
                    "command_recovery_exhausted"
                    if pending["recovery_code"] == "recovery_exhausted"
                    else "command_delivery_failed"
                )
            outbox = connection.execute(
                """SELECT status FROM broker_outbox WHERE deployment_namespace=%s AND scope_key=%s
                AND operation_id=%s AND aggregate_id=%s AND wake_generation=%s
                AND message_type='zebra.session.command.ready'""",
                (namespace, scope_key, pending["command_id"], event.session_id, generation),
            ).fetchone()
            return (
                "command_delivery_failed"
                if outbox is not None and outbox["status"] == "dead"
                else None
            )


def _identity(context: HostContextEnvelope) -> tuple[object, ...]:
    return (
        context.host_app_id,
        context.origin,
        context.namespace_id,
        context.workspace_ref,
        tuple(ref.resource_id for ref in context.resource_refs if ref.resource_type == "principal"),
    )


def _terminal(
    connection: Any, namespace: str, task_id: TaskId, event: SessionEvent, run_id: str
) -> bool:
    # Only canonical paired handoffs extend an execution into another Segment.
    return (
        connection.execute(
            """WITH RECURSIVE members AS (
          SELECT session_id, segment_index FROM execution_segments
          WHERE deployment_namespace=%s AND task_id=%s
        ), related AS (
          SELECT session_id FROM members WHERE session_id=%s
          UNION
          SELECT received.session_id FROM related parent
          JOIN session_events committed ON committed.deployment_namespace=%s
            AND committed.session_id=parent.session_id
            AND committed.event_type='session_handoff_committed'
            AND committed.projection_metadata_ready
            AND (committed.session_id<>%s OR committed.sequence>%s)
          JOIN session_events received
            ON received.deployment_namespace=committed.deployment_namespace
            AND received.event_type='session_handoff_received'
            AND received.projection_metadata_ready
            AND received.session_id=committed.projection_peer_segment_id
            AND received.projection_peer_segment_id=committed.session_id
            AND received.projection_handoff_id=committed.projection_handoff_id
          JOIN members child ON child.session_id=received.session_id
        )
        SELECT 1 FROM session_events terminal
        JOIN related ON related.session_id=terminal.session_id
        JOIN members current ON current.session_id=terminal.session_id
        JOIN members original ON original.session_id=%s
        WHERE terminal.deployment_namespace=%s AND terminal.event_type=ANY(%s)
        AND (current.segment_index, terminal.sequence)>(original.segment_index,%s)
        AND NOT EXISTS (
          SELECT 1 FROM session_events next JOIN members next_segment
          ON next_segment.session_id=next.session_id
          WHERE next.deployment_namespace=%s AND next.event_type='session_command_accepted'
          AND next.replay_header_ready AND NOT next.replay_internal_continuation
          AND next.replay_command_kind IN ('run','resume','message')
          AND next.replay_run_id IS DISTINCT FROM %s
          AND (next_segment.segment_index,next.sequence)>(original.segment_index,%s)
          AND (next_segment.segment_index,next.sequence)<(current.segment_index,terminal.sequence)
        ) LIMIT 1""",
            (
                namespace,
                task_id,
                event.session_id,
                namespace,
                event.session_id,
                event.sequence,
                event.session_id,
                namespace,
                [e.value for e in HANDLED_EVENTS],
                event.sequence,
                namespace,
                run_id,
                event.sequence,
            ),
        ).fetchone()
        is not None
    )
