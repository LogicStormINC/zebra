"""Read-only, scoped command outcomes for a verified AG-UI stream caller."""

from typing import Any
from uuid import UUID

from agent_core.contracts.broker_envelope import PrincipalScope
from agent_core.domain.events import SessionEvent
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_replay import TaskRunHeader

from agent_storage.postgres.command_wakeup import (
    _host_context_from_row,
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

    def supports_source_head(self, tasks: object) -> bool:
        from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore

        return (
            type(self) is PostgresCommandOutcomeReader
            and type(self).__call__ is _NATIVE_OUTCOME_CALL
            and type(tasks) is PostgresAgentTaskStore
            and tasks._database._dsn == self._database._dsn
            and tasks._database.deployment_namespace == self.deployment_namespace
        )

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
            return read_command_outcome(connection, namespace, run, host_context)


_NATIVE_OUTCOME_CALL = PostgresCommandOutcomeReader.__call__


def read_command_outcome(
    connection: Any, namespace: str, run: TaskRunHeader, host_context: HostContextEnvelope
) -> str | None:
    """Capture outcome metadata in the caller's fresh qualified Run snapshot."""
    if run.anchor is None:
        return None
    anchor = run.anchor
    scope = PrincipalScope(
        kind="principal",
        tenant_id=host_context.namespace_id,
        workspace_id=host_context.workspace_ref,
    )
    scope_key = command_scope_key(scope)
    row = connection.execute(
        "SELECT accepted,binding,terminal,pending,receipt,control,outbox FROM "
        "(WITH args AS (SELECT %s::text ns,%s::uuid tid,%s::bigint position,"
        "%s::uuid eid,%s::uuid sid,%s::bigint sequence,%s::text rid,%s::boolean control_only,"
        "%s::text scope_key,%s::text tenant,%s::text workspace,%s::text[] handled,true enabled),"
        + COMMAND_OUTCOME_BODY
        + ") captured",
        (
            namespace,
            run.task_id,
            anchor.task_sequence,
            anchor.event_id,
            anchor.segment_id,
            anchor.segment_sequence,
            run.run_id,
            run.control_only,
            scope_key,
            scope.tenant_id,
            scope.workspace_id,
            [e.value for e in HANDLED_EVENTS],
        ),
    ).fetchone()
    return command_outcome_from_row(connection, namespace, run, host_context, row)


def command_outcome_from_row(
    connection: Any,
    namespace: str,
    run: TaskRunHeader,
    host_context: HostContextEnvelope,
    row: Any,
) -> str | None:
    accepted = row["accepted"]
    if accepted is None:
        raise ValueError("command outcome has no unique canonical run binding")
    command_id = accepted.pop("command_id")
    if not isinstance(command_id, str) or len(command_id) > 36:
        raise ValueError("canonical command identity is invalid")
    UUID(command_id)
    event = SessionEvent.model_validate({**accepted, "payload": {"command_id": command_id}})
    binding = row["binding"]
    if binding is not None:
        binding["task_id"] = UUID(binding["task_id"])
    bound = _host_context_from_row(connection, namespace, event, binding)
    if bound is None or _identity(bound) != _identity(host_context):
        raise ValueError("command outcome Host identity conflicts")
    if not run.control_only and row["terminal"]:
        return None
    pending, receipt, control, outbox = (
        row[name] for name in ("pending", "receipt", "control", "outbox")
    )
    if pending is None:
        return None
    if receipt is not None and receipt["handled_event_id"] is not None:
        return None
    if receipt is not None and receipt["status"] == "requires_reconciliation":
        return "command_requires_reconciliation"
    if run.control_only and control is not None:
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
    return "command_delivery_failed" if outbox is not None and outbox["status"] == "dead" else None


def _identity(context: HostContextEnvelope) -> tuple[object, ...]:
    return (
        context.host_app_id,
        context.origin,
        context.namespace_id,
        context.workspace_ref,
        tuple(ref.resource_id for ref in context.resource_refs if ref.resource_type == "principal"),
    )


COMMAND_OUTCOME_BODY = """
accepted AS (
          SELECT event_id,session_id,sequence,event_type,actor,created_at,
            payload->>'command_id' AS command_id FROM session_events
          WHERE deployment_namespace=(SELECT ns FROM args) AND task_id=(SELECT tid FROM args)
AND task_sequence=(SELECT position FROM args)
            AND event_id=(SELECT eid FROM args) AND session_id=(SELECT sid FROM args) AND
sequence=(SELECT sequence FROM args) AND (SELECT enabled FROM args)
        ), binding AS (
          SELECT
session.namespace_id,segment.task_id,binding.snapshot_json,binding.binding_digest
          FROM session_projections session JOIN workspace_projections workspace
            ON workspace.deployment_namespace=session.deployment_namespace
            AND workspace.session_id=session.session_id
          JOIN execution_segments segment
            ON segment.deployment_namespace=session.deployment_namespace
            AND segment.session_id=session.session_id
          JOIN LATERAL (SELECT snapshot_json,binding_digest FROM task_binding_snapshots
            WHERE deployment_namespace=segment.deployment_namespace AND
task_id=segment.task_id
            ORDER BY binding_revision DESC LIMIT 1) binding ON TRUE
          WHERE session.deployment_namespace=(SELECT ns FROM args) AND
session.session_id=(SELECT sid FROM args) AND (SELECT enabled FROM args)
        ), terminal AS (SELECT 1 FROM (WITH RECURSIVE members AS (
          SELECT session_id, segment_index FROM execution_segments
          WHERE deployment_namespace=(SELECT ns FROM args) AND task_id=(SELECT tid FROM args)
        ), related AS (
          SELECT session_id FROM members WHERE session_id=(SELECT sid FROM args)
          UNION
          SELECT received.session_id FROM related parent
          JOIN session_events committed ON committed.deployment_namespace=(SELECT ns FROM
args)
            AND committed.session_id=parent.session_id
            AND committed.event_type='session_handoff_committed'
            AND committed.projection_metadata_ready
            AND (committed.session_id<>(SELECT sid FROM args) OR committed.sequence>(SELECT
sequence FROM args))
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
        JOIN members original ON original.session_id=(SELECT sid FROM args)
        WHERE terminal.deployment_namespace=(SELECT ns FROM args) AND
terminal.event_type=ANY((SELECT handled FROM args)::text[])
        AND (current.segment_index, terminal.sequence)>(original.segment_index,(SELECT
sequence FROM args))
        AND NOT EXISTS (
          SELECT 1 FROM session_events next JOIN members next_segment
          ON next_segment.session_id=next.session_id
          WHERE next.deployment_namespace=(SELECT ns FROM args) AND
next.event_type='session_command_accepted'
          AND next.replay_header_ready AND NOT next.replay_internal_continuation
          AND next.replay_command_kind IN ('run','resume','message')
          AND next.replay_run_id IS DISTINCT FROM (SELECT rid FROM args)
          AND (next_segment.segment_index,next.sequence)>(original.segment_index,(SELECT
sequence FROM args))
          AND
(next_segment.segment_index,next.sequence)<(current.segment_index,terminal.sequence)
        ) LIMIT 1 ) t WHERE NOT (SELECT control_only FROM args) AND (SELECT enabled FROM
args)), pending AS (
          SELECT p.* FROM session_command_pending p JOIN accepted a
            ON p.accepted_event_id=a.event_id AND p.session_id=a.session_id
            AND replace(p.command_id::text,'-','')=replace(lower(a.command_id),'-','')
          WHERE p.deployment_namespace=(SELECT ns FROM args) AND p.scope_key=(SELECT scope_key
FROM args) AND p.tenant_id=(SELECT tenant FROM args)
            AND p.workspace_id=(SELECT workspace FROM args)
        ), receipt AS (
          SELECT r.status,r.handled_event_id FROM command_handoff_receipts r JOIN pending p
            ON r.accepted_event_id=p.accepted_event_id AND r.session_id=p.session_id
            AND r.scope_key=p.scope_key AND r.command_id=p.command_id
            AND r.wake_generation=p.current_generation
          WHERE r.deployment_namespace=(SELECT ns FROM args)
        ), control AS (
          SELECT r.outcome FROM command_control_receipts r JOIN pending p
            ON r.accepted_event_id=p.accepted_event_id AND r.session_id=p.session_id
            AND r.scope_key=p.scope_key AND r.command_id=p.command_id
            AND r.wake_generation=p.current_generation
          WHERE r.deployment_namespace=(SELECT ns FROM args)
        ), outbox AS (
          SELECT r.status FROM broker_outbox r JOIN pending p
            ON r.scope_key=p.scope_key AND r.operation_id=p.command_id
            AND r.aggregate_id=p.session_id AND r.wake_generation=p.current_generation
          WHERE r.deployment_namespace=(SELECT ns FROM args) AND
r.message_type='zebra.session.command.ready'
        ) SELECT (SELECT to_jsonb(a) FROM accepted a) accepted,
          (SELECT to_jsonb(b) FROM binding b) binding,
          EXISTS(SELECT 1 FROM terminal) terminal,
          (SELECT to_jsonb(p) FROM pending p) pending,
          (SELECT to_jsonb(r) FROM receipt r) receipt,
          (SELECT to_jsonb(c) FROM control c) control,
          (SELECT to_jsonb(o) FROM outbox o) outbox
"""
