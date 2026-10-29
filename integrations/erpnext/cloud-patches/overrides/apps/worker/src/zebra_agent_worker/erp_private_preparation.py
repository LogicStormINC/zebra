"""ERP-only cold authority/physical check before the native two-second handoff."""
from datetime import UTC, datetime
import hashlib
from time import monotonic


def require_modern_private_delivery(settings, *, migrated, admission_enabled):
    if (settings.deployment != 'cloud' or settings.storage_authority != 'postgresql'
            or not migrated or admission_enabled is not True
            or not (settings.command_delivery.consume_enabled or settings.command_delivery.scan_fallback_enabled)):
        raise ValueError('ERP private workspaces require cloud PostgreSQL modern live command delivery')


def prepare_private_command(service, dsn, namespace, scope, accepted_id, raw, scope_mode):
    from agent_core.contracts.broker_envelope import PrincipalScope, ZebraCommandEnvelope, parse_broker_envelope
    from agent_core.domain.identifiers import SessionId
    from agent_core.domain.host_authority import HostGrantExpiredError
    from agent_core.domain.workspace_control import WorkspaceLifecycleState
    from agent_storage.postgres.command_rollout import command_scope_mode
    from agent_storage.postgres.command_wakeup import _canonical_json, command_scope_key
    from agent_storage.postgres.coverage_recovery_preparation import CoverageRecoveryDeferred
    from agent_storage.postgres.erp_private_workspace import private_facts, private_command_settlement, reject_private_coverage
    from agent_storage.postgres.task_admission import read_session_task_binding
    from zebra_agent_worker.erp_fresh_authority import (
        EarlyFreshRefusal, EarlyFreshUnavailable, FreshERPAuthority, require_early_authority,
    )

    policy = service._erp_workspace_containment
    if policy is None or namespace != 'erpnext' or policy._database._dsn != dsn:
        raise ValueError('private preparation composition mismatch')

    def read(connection):
        pending = connection.execute(
            'SELECT * FROM session_command_pending WHERE deployment_namespace=%s AND accepted_event_id=%s',
            (namespace, accepted_id),
        ).fetchone()
        if pending is None or (pending['scope_key'], pending['tenant_id'], pending['workspace_id']) != (
                command_scope_key(scope), scope.tenant_id, scope.workspace_id):
            raise ValueError('private preparation canonical scope mismatch')
        if pending['origin'] != 'live' or pending['status'] != 'pending':
            return None
        if raw is not None and parse_broker_envelope(raw).wake_generation != pending['current_generation']:
            return None  # Native handoff alone settles historical generations.
        outbox = connection.execute(
            "SELECT * FROM broker_outbox WHERE deployment_namespace=%s AND scope_key=%s AND operation_id=%s "
            "AND wake_generation=%s AND message_type='zebra.session.command.ready'",
            (namespace, pending['scope_key'], pending['command_id'], pending['current_generation']),
        ).fetchone()
        if outbox is None:
            raise ValueError('private preparation canonical outbox missing')
        body = _canonical_json(outbox['envelope_json']).encode()
        envelope = parse_broker_envelope(body)
        if (not isinstance(envelope, ZebraCommandEnvelope) or envelope.scope != scope
                or envelope.deployment_namespace != namespace or envelope.accepted_event_id != str(accepted_id)
                or envelope.aggregate_id != str(pending['session_id'])
                or envelope.operation_id != str(pending['command_id'])
                or envelope.accepted_sequence != pending['accepted_sequence']
                or envelope.wake_generation != pending['current_generation']
                or hashlib.sha256(body).hexdigest() != outbox['envelope_digest']
                or raw is not None and raw != body):
            raise ValueError('private preparation canonical envelope mismatch')
        if scope_mode is not None and ((command_scope_mode(connection, namespace, pending['scope_key']) == 'broker') != (scope_mode == 'broker')):
            raise CoverageRecoveryDeferred('private preparation scope mode changed')
        sid = SessionId(pending['session_id'])
        event = connection.execute(
            "SELECT session_id,sequence,event_type,payload->>'kind' AS kind FROM session_events "
            'WHERE deployment_namespace=%s AND event_id=%s', (namespace, accepted_id),
        ).fetchone()
        if event is None or (event['session_id'], event['sequence'], event['event_type'], event['kind']) != (
                sid, pending['accepted_sequence'], 'session_command_accepted', pending['command_kind']):
            raise ValueError('private preparation canonical command mismatch')
        if event['kind'] not in {'run', 'resume', 'message'}:
            return None
        # Classification uses native lineage only. Observation-only generations
        # keep the existing canonical policy refusal path and read no private body.
        try:
            identity, instance, _ = private_facts(connection, policy._workspace_control, sid)
        except (ValueError, TypeError, AttributeError):
            return None
        binding = read_session_task_binding(connection, namespace, sid)
        context = binding.host_capability.host_context
        if scope != PrincipalScope(kind='principal', tenant_id=context.namespace_id, workspace_id=context.workspace_ref):
            raise ValueError('private preparation Host scope mismatch')
        reject_private_coverage(connection, namespace, sid, accepted_id)
        signature = (tuple((k, str(pending[k])) for k in (
            'session_id','command_id','accepted_sequence','command_kind','scope_key','tenant_id','workspace_id',
            'current_generation','origin','status')), body, identity, binding.binding_digest,
            instance.model_dump_json())
        return signature, sid, instance, binding

    with policy._database.connect_task_io() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        if private_command_settlement(connection, namespace, scope, accepted_id, raw, scope_mode) is not None:
            return None
        snapshot = read(connection)
    if snapshot is None:
        return None
    signature, sid, instance, binding = snapshot
    # No native task-I/O scope remains open around the bounded HTTPS/UDS calls.
    try:
        fresh = FreshERPAuthority.for_execution(service, sid)
    except HostGrantExpiredError as error:
        raise CoverageRecoveryDeferred('private preparation grant expired') from error
    if fresh is None or fresh.binding.binding_digest != binding.binding_digest:
        raise CoverageRecoveryDeferred('private preparation binding changed')
    try:
        expires = require_early_authority(fresh.probe(datetime.now(UTC)))
    except (EarlyFreshRefusal, EarlyFreshUnavailable) as error:
        raise CoverageRecoveryDeferred('private preparation authority unavailable or refused') from error
    resolver = service._workspace_resolver
    guard = None if resolver is None else resolver._private_guard
    if guard is None:
        raise CoverageRecoveryDeferred('private preparation physical guard missing')
    try:
        guard(sid, instance, allow_allocate=instance.state is WorkspaceLifecycleState.PENDING)
    except (ValueError, OSError) as error:
        raise CoverageRecoveryDeferred('private preparation physical verification refused') from error
    try:
        expires = require_early_authority(fresh.probe(datetime.now(UTC)))
    except (EarlyFreshRefusal, EarlyFreshUnavailable) as error:
        raise CoverageRecoveryDeferred('private preparation authority changed during physical verification') from error
    deadline = monotonic() + (expires - datetime.now(UTC)).total_seconds()

    def revalidate(connection, ns, candidate):
        if ns != namespace or candidate != accepted_id or monotonic() >= deadline or datetime.now(UTC) >= expires:
            raise CoverageRecoveryDeferred('private preparation proof expired or mismatched')
        try:
            current = read(connection)
        except ValueError as error:
            raise CoverageRecoveryDeferred('private preparation canonical facts changed') from error
        if current is None or current[0] != signature:
            raise CoverageRecoveryDeferred('private preparation canonical facts changed')
        if monotonic() >= deadline or datetime.now(UTC) >= expires:
            raise CoverageRecoveryDeferred('private preparation proof expired')
    return revalidate
