"""Atomic native human input, attachment metadata, projections and replay receipt."""
from dataclasses import replace
from uuid import UUID

from psycopg.types.json import Jsonb
from agent_core.application import SessionMessageAppendCommand, SessionMessageAppendService, current_turn, project_turns
from agent_core.application.session_attachments import attach_refs_to_user_event
from agent_core.application.session_projection import apply_event
from agent_core.application.workspace_projection import apply_event as apply_workspace
from agent_core.domain.identifiers import TaskId
from agent_core.ports.idempotency_store import IdempotencyRecord
from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.http_input_attachments import admit_http_input, check_input_authority
from agent_storage.postgres.projections import get_session_in_transaction, save_session_in_transaction
from agent_storage.postgres.workspaces import get_workspace_in_transaction, save_workspace_in_transaction
from agent_storage.postgres.task_admission import _insert_or_load_idempotency, _read_task_binding
from agent_storage.postgres.task_index_transactions import _lock_task, rebuild_task_in_transaction


def claim_input_receipt(connection, namespace, prepared):
    pending = IdempotencyRecord(action=prepared.action, idempotency_key=prepared.idempotency_key,
        request_hash=prepared.request_hash, status_code=201, response_body={}, created_at=prepared.event.created_at)
    existing = _insert_or_load_idempotency(connection, namespace, pending)
    if existing is not None and existing.request_hash != prepared.request_hash:
        raise ValueError('HTTP input idempotency conflict')
    if existing is not None and not existing.response_body:
        raise ValueError('HTTP input receipt requires reconciliation')
    # The placeholder is never committed: materialization replaces it in this
    # same transaction, or the entire claim/input/handoff rolls back.
    return existing


def materialize_http_input(connection, namespace, prepared, *, session, workspace, events, rolled_over=False):
    task_id = TaskId(UUID(prepared.attachments.authority.task_id))
    _lock_task(connection, namespace, task_id)
    binding = _read_task_binding(connection, namespace, task_id)
    if binding is None:
        raise ValueError('HTTP input Task binding is missing')
    check_input_authority(connection, namespace, prepared.attachments.authority, binding)
    target = connection.execute('SELECT active_segment_id FROM agent_tasks WHERE deployment_namespace=%s AND task_id=%s',
        (namespace, task_id)).fetchone()
    if target is None or target['active_segment_id'] != session.session_id:
        raise ValueError('HTTP input active Segment changed')
    draft = prepared.event
    if draft.session_id != session.session_id or prepared.attachments.session_id != session.session_id:
        raise ValueError('HTTP input target conflicts')
    event = SessionMessageAppendService().build_event(session=session, next_sequence=session.current_sequence+1,
        command=SessionMessageAppendCommand(content=draft.payload['content'],
            clarification_id=draft.payload.get('clarification_id'),
            model_profile=draft.payload.get('model_profile'),reasoning_effort=draft.payload.get('reasoning_effort'),
            appended_at=draft.created_at,prior_human_turns=len(project_turns(events)),
            open_turn_exists=current_turn(events) is not None))
    event = event.model_copy(update={'event_id':draft.event_id,
        'idempotency_key':f'http-input:{prepared.idempotency_key}'})
    batch = replace(prepared.attachments, entries=tuple(replace(entry,
        reservation=entry.reservation.model_copy(update={'intended_event_sequence':event.sequence}))
        for entry in prepared.attachments.entries))
    event = attach_refs_to_user_event(event, tuple(entry.reference for entry in batch.entries))
    canonical = append_event_in_transaction(connection, namespace, event)
    save_session_in_transaction(connection, namespace, apply_event(session, canonical))
    save_workspace_in_transaction(connection, namespace, apply_workspace(workspace, canonical))
    admit_http_input(connection, namespace, batch, canonical, binding)
    # Allocate native global coordinates before freezing the replay receipt;
    # the normally deferred trigger otherwise leaves a stale root highwater.
    connection.execute("SET CONSTRAINTS session_events_allocate_task_position IMMEDIATE")
    task = rebuild_task_in_transaction(connection, namespace, task_id)
    body = dict(task_id=str(task_id),session_id=str(task_id),active_segment_id=str(session.session_id),
        active_segment_sequence=canonical.sequence,sequence=canonical.sequence,current_sequence=task.current_sequence,
        appended=True,content=canonical.payload['content'],idempotency_key=prepared.idempotency_key,
        attachments=[entry.reference.to_mapping() for entry in batch.entries])
    if rolled_over:body['rolled_over']=True
    if canonical.payload.get('clarification_id'):
        body.update(clarification_resolved=True,clarification_id=canonical.payload['clarification_id'])
    updated = connection.execute('''UPDATE control_plane_idempotency_records SET response_body=%s
        WHERE deployment_namespace=%s AND action=%s AND idempotency_key=%s AND request_hash=%s''',
        (Jsonb(body),namespace,prepared.action,prepared.idempotency_key,prepared.request_hash))
    if updated.rowcount != 1:
        raise ValueError('HTTP input atomic replay receipt is missing')
    return IdempotencyRecord(action=prepared.action,idempotency_key=prepared.idempotency_key,
        request_hash=prepared.request_hash,status_code=201,response_body=body,created_at=canonical.created_at)


def append_http_input(database, prepared):
    from agent_storage.postgres.leases import lock_session_lease_boundary
    from agent_storage.postgres.events import _event_from_row
    namespace, session_id = database.deployment_namespace, prepared.event.session_id
    with database.connect() as connection:
        existing = claim_input_receipt(connection,namespace,prepared)
        if existing is not None:
            task_id=TaskId(UUID(prepared.attachments.authority.task_id))
            _lock_task(connection,namespace,task_id)
            binding=_read_task_binding(connection,namespace,task_id)
            if binding is None:raise ValueError('HTTP input Task binding missing')
            check_input_authority(connection,namespace,prepared.attachments.authority,binding)
            return existing
        lock_session_lease_boundary(connection,namespace,session_id)
        stream = connection.execute('SELECT current_version FROM session_streams WHERE deployment_namespace=%s AND session_id=%s FOR UPDATE',
            (namespace,session_id)).fetchone()
        session=get_session_in_transaction(connection,namespace,session_id)
        workspace=get_workspace_in_transaction(connection,namespace,session_id)
        if (stream is None or session is None or workspace is None or session.current_sequence != stream['current_version']
            or workspace.current_sequence != stream['current_version'] or prepared.event.sequence != stream['current_version']+1):
            raise ValueError('HTTP input stream revision changed')
        rows=connection.execute('''SELECT event_id,session_id,sequence,event_type,payload,actor,created_at,
            causation_id,correlation_id,idempotency_key,policy_version,model_profile FROM session_events
            WHERE deployment_namespace=%s AND session_id=%s ORDER BY sequence''',(namespace,session_id)).fetchall()
        return materialize_http_input(connection,namespace,prepared,session=session,workspace=workspace,
            events=[_event_from_row(row) for row in rows])
