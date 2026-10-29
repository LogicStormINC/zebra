"""One assertion-only check; run in pinned105 Worker with overlay_imports.

No real model, network, database, allocator or production mutations. SQL seams
use strict recording doubles; actual PostgreSQL concurrency remains a separate gate.
"""
import overlay_imports
import os
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.contracts.broker_envelope import PrincipalScope
from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef, HostTechnicalLimits
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import WorkerLease, LeaseFence
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.task_bindings import (
    TaskBindingSnapshot, AgentCapabilityCeilingSnapshot, HostCapabilitySnapshot, host_context_digest,
)
from agent_core.domain.workspace_control import WorkspaceInstance, WorkspaceSource, WorkspaceSourceKind
from agent_storage.postgres import erp_workspace_policy as policy
from agent_storage.postgres import command_wakeup_handoff as handoff
from agent_storage.postgres import command_read_preflight as preflight
from agent_storage.postgres import projections
from agent_storage.postgres.command_wakeup import command_scope_key
from zebra_agent_worker import execution, execution_recovery, cloud_memory_recovery
from zebra_agent_worker.command_consumer import SessionCommandConsumer
from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.command_rejections import command_rejected

NOW = datetime.now(UTC)
SID = SessionId(uuid4())
WID = uuid4()
THREAD = str(uuid4())
REF = 'erp-u-' + 'a' * 40
LOCATOR = f'erpnext://private-workspace/v1/{THREAD}/{REF}'
CAPS = capability_set(['agent.execute', 'evidence.read'])
CONTEXT = HostContextEnvelope(grant_id='qa', host_app_id='erpnext', namespace_id='erpnext',
    workspace_ref=REF, resource_refs=(HostResourceRef(type='thread', id=THREAD),
    HostResourceRef(type='principal', id='qa-user')), scopes=('agent.run',),
    limits=HostTechnicalLimits(max_runtime_seconds=10, max_model_tokens=10, max_artifact_bytes=10),
    origin='https://erpnext.zebra.local', policy_version='v1', expires_at=NOW + timedelta(minutes=5))
HOST = HostCapabilitySnapshot(host_app_id='erpnext', authority_issuer='https://erpnext.zebra.local',
    namespace_id='erpnext', grant_digest=host_context_digest(CONTEXT), host_context=CONTEXT,
    connector_id='erp', connector_profile_revision=1, connector_profile_digest='c'*64,
    manifest_digest='d'*64, capabilities=CAPS, resource_binding_digest='e'*64, bound_at=NOW)
BINDING = TaskBindingSnapshot(task_id=str(SID),
    agent_capability_ceiling=AgentCapabilityCeilingSnapshot(definition_snapshot_digest='b'*64,
        capability_profile_ref='profile/default@1', capabilities=CAPS, resolved_at=NOW),
    host_capability=HOST, zebra_policy_digest='f'*64, effective_capabilities=CAPS,
    binding_revision=1, bound_at=NOW)
INSTANCE = WorkspaceInstance(workspace_id=WID, deployment_namespace='erpnext',
    source=WorkspaceSource(kind='host_reference', locator=LOCATOR), state='pending',
    owner_session_id=SID, quota_bytes=100)


def refuses(fn, code):
    try:
        fn()
    except policy.ERPWorkspacePolicyRefusal as error:
        assert error.code == code, error.code
        assert not isinstance(error, execution.WorkerExecutionError)
    else:
        raise AssertionError('Execution was not refused: ' + code)


with patch.dict(os.environ, {policy.ERP_CONTAINMENT_ENV: 'disabled'}):
    assert not policy.containment_enabled('erpnext')
    assert policy.eligible_execution_sql('trench') == ''
with patch.dict(os.environ, {policy.ERP_CONTAINMENT_ENV: 'enabled'}):
    assert policy.eligible_execution_sql('erpnext') == ' AND FALSE '
    for namespace in ('trench', None):
        try: policy.containment_enabled(namespace)
        except ValueError: pass
        else: raise AssertionError('Cross-deployment configuration accepted')

assert policy.is_private_generation(BINDING, INSTANCE, task_id=str(SID))
for locator in ('/var/lib/zebra/erpnext-workspaces', LOCATOR+'/', LOCATOR+'?x=1',
                LOCATOR.replace('erpnext://', 'erpnext:/'), LOCATOR.replace(THREAD, str(uuid4())),
                LOCATOR.replace(REF, 'erp-u-'+ 'A'*40), LOCATOR.replace('v1/', 'v1/../v1/')):
    instance = INSTANCE.model_copy(update={'source': INSTANCE.source.model_copy(update={'locator':locator})})
    assert not policy.is_private_generation(BINDING, instance, task_id=str(SID)), locator
for changed in ({'authority_issuer':'https://other.example'}, {'host_app_id':'trench'},
                {'namespace_id':'other'}, {'grant_digest':'0'*64}):
    assert not policy.is_private_generation(BINDING.model_copy(update={
        'host_capability': HOST.model_copy(update=changed)}), INSTANCE, task_id=str(SID))
for resources in ((HostResourceRef(type='principal',id='user'),),
                  CONTEXT.resource_refs+(HostResourceRef(type='thread',id=str(uuid4())),),
                  CONTEXT.resource_refs+(HostResourceRef(type='principal',id='other'),)):
    context = CONTEXT.model_copy(update={'resource_refs':resources})
    host = HOST.model_copy(update={'host_context':context,'grant_digest':host_context_digest(context)})
    assert not policy.is_private_generation(BINDING.model_copy(update={'host_capability':host}),
                                             INSTANCE, task_id=str(SID))

class Row:
    def __init__(self, value): self.value = value
    def fetchone(self): return self.value
    def fetchall(self): return []

class Database:
    deployment_namespace = 'erpnext'
    def __init__(self, connection): self.connection = connection
    @contextmanager
    def connect_task_io(self): yield self.connection
    connect = connect_task_io

class Facts:
    def __init__(self): self.statements = []
    def execute(self, sql, args=()):
        self.statements.append((sql,args))
        if 'FROM agent_tasks task' in sql: return Row({'task_id':SID})
        if sql.startswith('SET TRANSACTION'): return Row(None)
        raise AssertionError(sql)

facts = Facts()
control = NS(deployment_namespace='erpnext', get_in_transaction=Mock(return_value=INSTANCE))
gate = object.__new__(policy.ERPWorkspaceContainment)
gate._database, gate._workspace_control = Database(facts), control
with patch('agent_storage.postgres.task_admission.read_session_task_binding', return_value=BINDING), \
     patch('agent_storage.postgres.workspaces.get_workspace_in_transaction') as workspace_read:
    for reference in (f'workspace://{WID}', f'workspace:/{WID}'):
        workspace_read.return_value = NS(workspace_root=reference)
        refuses(lambda:gate.require(SID), policy.PRIVATE_NOT_ACTIVATED)
    # Actual native API leaves control owner NULL; only the complete canonical
    # Task/active-Segment/projection/UUID join makes it a private generation.
    control.get_in_transaction.return_value = INSTANCE.model_copy(update={'owner_session_id':None})
    refuses(lambda:gate.require(SID), policy.PRIVATE_NOT_ACTIVATED)
    control.get_in_transaction.return_value = INSTANCE.model_copy(update={'owner_session_id':uuid4()})
    refuses(lambda:gate.require(SID), policy.LEGACY_OBSERVATION_ONLY)
    control.get_in_transaction.return_value = INSTANCE
    for reference in ('/var/lib/zebra/erpnext-workspaces', f'workspace://{WID}/', str(WID), 'unknown'):
        workspace_read.return_value = NS(workspace_root=reference)
        refuses(lambda:gate.require(SID), policy.LEGACY_OBSERVATION_ONLY)
    for state in ('pending','uncertain','ready'):
        instance = INSTANCE.model_copy(update={'state':state,
            'source':INSTANCE.source.model_copy(update={'locator':'/var/lib/zebra/erpnext-workspaces'})})
        control.get_in_transaction.return_value = instance
        workspace_read.return_value = NS(workspace_root=f'workspace://{WID}')
        refuses(lambda:gate.require(SID), policy.LEGACY_OBSERVATION_ONLY)
assert all(not sql.lstrip().startswith(('INSERT','UPDATE','DELETE')) for sql,_ in facts.statements)

# Every existing execution entrypoint reaches the same last defense. Use the real
# heartbeat and verify release on refusal, with no setup failure finalizer.
lease = WorkerLease(session_id=SID,
    fence=LeaseFence(control_plane_epoch=uuid4(), fencing_token=1, owner_instance_id='qa'),
    acquired_at=NOW, heartbeat_at=NOW, expires_at=NOW+timedelta(hours=1))
claimed = ClaimedSession(lease=lease, recovery=NS(session=NS(status=SessionStatus.RUNNING),workspace=NS(),is_terminal=False))
claims = NS(claim_session=Mock(return_value=claimed), recover_lease=Mock(return_value=claimed),
    heartbeat_lease=Mock(return_value=lease),release_lease=Mock())
service = object.__new__(execution.SessionExecutionService)
service._erp_workspace_containment = NS(require=Mock(side_effect=policy.ERPWorkspacePolicyRefusal(policy.LEGACY_OBSERVATION_ONLY)))
service._projection_recorder_factory = NS(completion_reader=None)
service._claim_service = claims
service._resume_service = NS(require_resumable=lambda *args,**kwargs:NS(claimed=claimed))
service._execution_namespace = 'erpnext'
with ExitStack() as stack:
    forbidden = [stack.enter_context(patch.object(module,name, side_effect=AssertionError(name)))
        for module,name in ((execution,'recover_execution_progress'),(execution,'prepare_execution_inputs'),
                            (execution_recovery,'finalize_worker_setup_failure'))]
    for entry in (lambda:service.execute_session(SID,worker_id='qa'),
                  lambda:service.execute_claimed_session(lease),
                  lambda:execution_recovery.execute_claimed_with_stale_retry(service,claimed,
                      started_at=NOW,ownership_check=lambda:None)):
        refuses(entry, policy.LEGACY_OBSERVATION_ONLY)
    assert claims.release_lease.call_count == 2
    assert all(check.call_count == 0 for check in forbidden)

# Independent memory path refuses before recorder/finalization/reservation/model.
memory = object.__new__(cloud_memory_recovery.CloudMemoryFinalizationRecovery)
memory._claim_service = claims
memory._erp_workspace_containment = service._erp_workspace_containment
with patch.object(cloud_memory_recovery,'finalize_cloud_memory') as finalize, \
     patch.object(cloud_memory_recovery,'_reserve_title_attempt') as reserve, \
     patch.object(cloud_memory_recovery,'_mark_memory_recovered') as receipt:
    refuses(lambda:memory.recover(SID,worker_id='qa',recovered_at=NOW,lease_ttl_seconds=30),
            policy.LEGACY_OBSERVATION_ONLY)
    assert not finalize.called and not reserve.called and not receipt.called
assert claims.release_lease.call_count == 3

# A stale recovery retries through the exact same source policy, never around it.
service._recovery_service = NS(recover_session=Mock(return_value=claimed.recovery))
with patch.object(execution, 'recover_committed_completion',
        side_effect=[execution_recovery.StaleExecutionSnapshot('QA'), None]), \
     patch.object(execution, 'prepare_execution_inputs') as prepare:
    refuses(lambda:execution_recovery.execute_claimed_with_stale_retry(service,claimed,
        started_at=NOW,ownership_check=lambda:None), policy.LEGACY_OBSERVATION_ONLY)
    assert service._recovery_service.recover_session.call_count == 1 and not prepare.called

# Missing native policy/binding dependencies are a startup error, not an opt-out.
with patch.dict(os.environ,{policy.ERP_CONTAINMENT_ENV:'enabled'}):
    try:
        execution.SessionExecutionService(database_path=None,claim_service=claims,
            resume_service=None,deployment_namespace='erpnext')
    except ValueError as error:assert 'requires native' in str(error)
    else:raise AssertionError('Missing policy accepted at startup')

# Legacy canonical rejection uses the fingerprint receipt, before append/lease.
class Receipts:
    def __init__(self): self.rows = {}
    def get(self,*,action,idempotency_key): return self.rows.get((action,idempotency_key))
    def save(self,record): self.rows.setdefault((record.action,record.idempotency_key),record); return record

receipts = Receipts()
stores = NS(events=Mock(),sessions=Mock(),workspaces=Mock(),idempotency=receipts)
legacy = SessionCommandConsumer(stores, service,
    command_sessions=lambda *args:[NS(session_id=SID,current_sequence=1,status=SessionStatus.READY)])
legacy._append_message = Mock(side_effect=AssertionError('MESSAGE'))
legacy._cancel = Mock()
for kind in (SessionCommandKind.RUN,SessionCommandKind.RESUME,SessionCommandKind.MESSAGE,
             SessionCommandKind.STOP,SessionCommandKind.CANCEL):
    command = SessionCommand(session_id=SID,kind=kind,expected_revision=1,
        idempotency_key=kind.value,payload={'content':'QA'} if kind is SessionCommandKind.MESSAGE else {})
    event = SessionEvent.create(session_id=SID,sequence=2,event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,payload=command.event_payload(),idempotency_key=command.idempotency_key)
    legacy._command_reader = lambda *args:event
    result = legacy.consume_once(worker_id='qa',lease_ttl_seconds=30)
    if kind in {SessionCommandKind.STOP,SessionCommandKind.CANCEL}:
        assert result.status == 'executed'
    else:
        assert result.reason == policy.LEGACY_OBSERVATION_ONLY
        assert command_rejected(receipts,event)
        record = next(r for r in receipts.rows.values() if r.idempotency_key == str(event.event_id))
        assert record.status_code == 409
        size = len(receipts.rows)
        legacy.consume_once(worker_id='qa',lease_ttl_seconds=30)
        assert len(receipts.rows) == size
assert legacy._cancel.call_count == 2 and not legacy._append_message.called
assert not stores.events.append.called

# Ready/memory database predicates are applied before LIMIT: no ineligible source
# occupies the candidate batch, including currently unactivated private sources.
class Queries:
    def __init__(self): self.sql = []
    def execute(self,sql,args=()): self.sql.append(sql); return Row(None)
queries=Queries()
store=object.__new__(projections.PostgresProjectionStore);store._database=Database(queries)
with patch.dict(os.environ,{policy.ERP_CONTAINMENT_ENV:'enabled'}):
    assert store.list_ready_sessions(limit=1) == []
    assert store.list_memory_recovery_sessions(limit=1,recovery_action='qa') == []
    assert all(sql.index('AND FALSE') < sql.index('LIMIT') for sql in queries.sql)
with patch.dict(os.environ,{policy.ERP_CONTAINMENT_ENV:'disabled'}):
    queries.sql.clear();store.list_ready_sessions(limit=1)
    assert 'AND FALSE' not in queries.sql[0]

# Modern prelude never enters MESSAGE preparation; formal handoff writes only
# exact dead/code metadata, without touching receipts or acquiring a new fence.
scope=PrincipalScope(kind='principal',tenant_id='erpnext',workspace_id=REF)
EID,CID=uuid4(),uuid4()
pending=dict(scope_key=command_scope_key(scope),tenant_id='erpnext',workspace_id=REF,
    session_id=SID,accepted_event_id=EID,command_id=CID,current_generation=0,status='pending',origin='live',command_kind='message',accepted_sequence=2)
outbox=dict(wake_generation=0,envelope_json=dict(
    message_id=str(uuid4()),schema_version=1,deployment_namespace='erpnext',aggregate_id=str(SID),
    operation_id=str(CID),wake_generation=0,idempotency_key='qa',correlation_id='qa',causation_id=None,
    occurred_at=NOW.isoformat(),traceparent=None,payload_ref=dict(kind='zebra_command',id=str(CID)),
    message_type='zebra.session.command.ready',scope=scope.model_dump(),accepted_event_id=str(EID),
    accepted_sequence=2))
class Commands:
    def __init__(self,receipt=None,active=False,terminal=False):
        self.pending=dict(pending);self.receipt=(dict(receipt,accepted_event_id=EID,session_id=SID)
            if receipt is not None else None);self.active=active;self.terminal=terminal;self.writes=[]
    def execute(self,sql,args=()):
        if 'FROM session_command_pending' in sql: return Row(self.pending)
        if 'FROM broker_outbox' in sql: return Row(outbox)
        if 'FROM command_retirements' in sql:return Row(None)
        if 'FROM command_handoff_receipts' in sql:return Row(self.receipt)
        if 'SELECT payload FROM session_events' in sql:return Row({'payload':{'kind':'message'}})
        if sql.startswith("UPDATE session_command_pending"):
            if self.pending['status']=='pending':
                self.pending.update(status='dead',recovery_code=args[0]);self.writes.append((sql,args))
            return Row(None)
        if sql.startswith('SET LOCAL') or 'pg_advisory_xact_lock' in sql:return Row(None)
        raise AssertionError(sql)

with ExitStack() as stack, patch.dict(os.environ,{policy.ERP_CONTAINMENT_ENV:'enabled'}):
    for module,name,value in ((handoff,'_validate',None),(handoff,'_check_inbox',None),
        (handoff,'reject_missing_command_consumer',None),(handoff,'pin_command_consumer',None),
        
        (handoff,'recovery_approval',None)):
        stack.enter_context(patch.object(module,name,side_effect=(lambda c,*a:c) if value=='connection' else None,return_value=value))
    stack.enter_context(patch.object(handoff,'prepare_command_handoff',side_effect=AssertionError('coverage preparation')))
    stack.enter_context(patch.object(handoff,'prepared_recovery_connection',side_effect=AssertionError('prepared recovery wrapper')))
    guard=NS(require=Mock(side_effect=policy.ERPWorkspacePolicyRefusal(policy.LEGACY_OBSERVATION_ONLY)))
    stack.enter_context(patch.object(policy,'containment_for_database',return_value=guard))
    acquire=stack.enter_context(patch.object(handoff,'acquire_lease_in_transaction',side_effect=AssertionError('lease')))
    append=stack.enter_context(patch.object(handoff,'append_command_message',side_effect=AssertionError('MESSAGE')))
    for receipt,active,terminal,expected in ((None,False,False,1),(None,True,False,0),
        (dict(handled_event_id=uuid4()),False,False,0),
        (dict(handled_event_id=None,started_event_id=uuid4()),False,False,0),
        (None,False,True,0)):
        connection=Commands(receipt,active,terminal)
        with patch.object(handoff,'_database',return_value=Database(connection)), \
             patch.object(handoff,'prepare_command_candidate',side_effect=AssertionError('candidate preparation')), \
             patch('agent_storage.postgres.leases.read_current_lease',return_value=lease if active else None), \
             patch.object(handoff,'_terminal_session',return_value=terminal):
            for _ in range(2):
                result=handoff.handoff_command('qa',deployment_namespace='erpnext',scope=scope,
                    accepted_event_id=EID,owner_instance_id='qa',ttl=timedelta(seconds=30))
                assert result.lease is None
            assert len(connection.writes)==expected
            if expected:assert connection.pending['recovery_code']==policy.LEGACY_OBSERVATION_ONLY
    assert not acquire.called and not append.called
    connection=Commands()
    event=NS(event_type=EventType.SESSION_COMMAND_ACCEPTED,payload={'kind':'message'})
    with patch.object(preflight,'_database',return_value=Database(connection)), \
         patch.object(preflight,'command_event_at',return_value=event), \
         patch.object(preflight,'finish_command_read_state') as finish, \
         patch.dict(os.environ,{policy.ERP_CONTAINMENT_ENV:'enabled'}):
        assert preflight.prepare_command_candidate('qa','erpnext',scope,EID,None,0,None,message_only=True) is None
        assert not finish.called and not connection.writes
# Regression: real NativeCoverageRecoveryCheck must not enter preparation before
# containment. Its original prepare/_prepare chain is supplied intact; forbidden
# boundaries fail loudly instead of returning the old test's harmless None.
from zebra_agent_worker.coverage_recovery_preparation import NativeCoverageRecoveryCheck, RecoveryArtifactReads
from zebra_agent_worker import coverage_recovery as native_recovery

native_database = NS(connect=Mock(side_effect=AssertionError('native recovery preparation entered')))
checker = NativeCoverageRecoveryCheck(
    NS(deployment_namespace='erpnext', metadata=NS(_database=native_database)), NS())
original_prepare = NativeCoverageRecoveryCheck.prepare
with ExitStack() as stack:
    prepare_spy = stack.enter_context(patch.object(NativeCoverageRecoveryCheck, 'prepare',
        autospec=True, side_effect=original_prepare))
    forbidden = [stack.enter_context(patch.object(module, name,
        side_effect=AssertionError('forbidden containment boundary: '+name))) for module,name in (
            (native_recovery, 'prepare_recovery_authority'),
            (native_recovery, 'frozen_or_discovered_manifest'),
            (native_recovery.HostCoverageSnapshotSource, '_get_descriptor'),
            (native_recovery, 'load_official_model_policy'),
            (RecoveryArtifactReads, '_read_record'),
        )]
    candidate = stack.enter_context(patch.object(handoff, 'prepare_command_candidate',
        side_effect=AssertionError('candidate preparation entered')))
    # These are pure native SQL security checks, retained before denial. Keep
    # the real functions and observe them; a non-strict command yields no pin.
    security_reject = stack.enter_context(patch.object(handoff, 'reject_missing_command_consumer',
        wraps=handoff.reject_missing_command_consumer))
    security_pin = stack.enter_context(patch.object(handoff, 'pin_command_consumer',
        wraps=handoff.pin_command_consumer))
    for name in ('_validate','_check_inbox','recovery_approval'):
        stack.enter_context(patch.object(handoff,name,return_value=None))
    stack.enter_context(patch.object(policy,'containment_for_database',return_value=guard))
    stack.enter_context(patch('agent_storage.postgres.leases.read_current_lease',return_value=None))
    stack.enter_context(patch.object(handoff,'_terminal_session',return_value=False))
    class StrictCommands(Commands):
        def execute(self,sql,args=()):
            if 'SELECT 1 FROM command_coverage_requirements' in sql: return Row(None)
            if 'SELECT session_id,payload FROM session_events' in sql:
                return Row(dict(session_id=SID,payload={'kind':'message'}))
            if 'SELECT t.task_id,t.root_session_id' in sql: return Row(None)
            return super().execute(sql,args)
    connection=StrictCommands()
    with patch.object(handoff,'_database',return_value=Database(connection)), \
         patch.dict(os.environ,{policy.ERP_CONTAINMENT_ENV:'enabled'}):
        result=handoff.handoff_command('qa',deployment_namespace='erpnext',scope=scope,
            accepted_event_id=EID,owner_instance_id='qa',ttl=timedelta(seconds=30),coverage_check=checker)
        assert result.status is handoff.HandoffStatus.REQUIRES_RECONCILIATION
        assert connection.pending['recovery_code']==policy.LEGACY_OBSERVATION_ONLY
    assert security_reject.call_count==1 and security_pin.call_count==1
    assert not candidate.called and not prepare_spy.called and not native_database.connect.called
    assert all(not boundary.called for boundary in forbidden)
    # Canonical validation still precedes denial/ACK; malformed candidates
    # cannot use containment to acquire an apparently valid terminal outcome.
    connection=StrictCommands()
    previous_refusals=guard.require.call_count
    with patch.object(handoff,'_database',return_value=Database(connection)), \
         patch.object(handoff,'_validate',side_effect=ValueError('canonical mismatch')), \
         patch.dict(os.environ,{policy.ERP_CONTAINMENT_ENV:'enabled'}):
        try:
            handoff.handoff_command('qa',deployment_namespace='erpnext',scope=scope,
                accepted_event_id=EID,owner_instance_id='qa',ttl=timedelta(seconds=30),coverage_check=checker)
        except ValueError as error:assert str(error)=='canonical mismatch'
        else:raise AssertionError('Unvalidated canonical command was ACKed')
    assert not connection.writes and guard.require.call_count==previous_refusals
    class ControlCommands(StrictCommands):
        def execute(self,sql,args=()):
            if 'SELECT payload FROM session_events' in sql:return Row({'payload':{'kind':'stop'}})
            return super().execute(sql,args)
    connection=ControlCommands()
    with patch.object(handoff,'_database',return_value=Database(connection)), \
         patch.dict(os.environ,{policy.ERP_CONTAINMENT_ENV:'enabled'}):
        result=handoff.handoff_command('qa',deployment_namespace='erpnext',scope=scope,
            accepted_event_id=EID,owner_instance_id='qa',ttl=timedelta(seconds=30),coverage_check=checker)
        assert result.status is handoff.HandoffStatus.UNSUPPORTED_FOR_EXECUTION_HANDOFF
    assert not connection.writes and guard.require.call_count==previous_refusals
    # A qualified strict consumer is re-pinned and checked AFTER tentative
    # metadata writes. Expiry must raise so the real outer transaction rolls back.
    connection=StrictCommands()
    capability=NS()
    with patch.object(handoff,'_database',return_value=Database(connection)), \
         patch.object(handoff,'pin_command_consumer',return_value=capability) as pin, \
         patch.object(handoff,'check_worker_capability_clock',
             side_effect=handoff.WorkerCapabilityLostError('expired')) as clock, \
         patch.dict(os.environ,{policy.ERP_CONTAINMENT_ENV:'enabled'}):
        try:
            handoff.handoff_command('qa',deployment_namespace='erpnext',scope=scope,
                accepted_event_id=EID,owner_instance_id='qa',ttl=timedelta(seconds=30),coverage_check=checker)
        except handoff.WorkerCapabilityLostError:pass
        else:raise AssertionError('Expired capability committed a refusal')
        assert len(connection.writes)==1 and pin.call_count==2 and clock.call_count==1
        assert pin.call_args.kwargs=={'lock_task_authority':True}
    assert not candidate.called and not prepare_spy.called and not native_database.connect.called
    assert all(not boundary.called for boundary in forbidden)
    # Disabled keeps candidate -> security -> native prepare ordering. The real
    # native prepare/_prepare chain reaches its DB boundary and stops at a strict
    # sentinel, before any real I/O can occur in this assertion-only check.
    order=[]
    candidate.side_effect=lambda *args,**kwargs:order.append('candidate')
    security_reject.side_effect=lambda *args,**kwargs:order.append('security')
    def enter_native(self,*args,**kwargs):
        order.append('native_prepare')
        return original_prepare(self,*args,**kwargs)
    prepare_spy.side_effect=enter_native
    with patch.object(handoff,'_database',return_value=Database(StrictCommands())), \
         patch.dict(os.environ,{policy.ERP_CONTAINMENT_ENV:'disabled'}):
        try:
            handoff.handoff_command('qa',deployment_namespace='erpnext',scope=scope,
                accepted_event_id=EID,owner_instance_id='qa',ttl=timedelta(seconds=30),coverage_check=checker)
        except AssertionError as error: assert str(error)=='native recovery preparation entered'
        else: raise AssertionError('Disabled native preparation was silently skipped')
    assert order==['candidate','security','native_prepare'],order
    assert prepare_spy.call_count==1 and native_database.connect.call_count==1
    assert all(not boundary.called for boundary in forbidden)

print('PASS ERP source classification; shared execution and memory refusal with real heartbeat release; '
      'legacy exact409 receipt and STOP/CANCEL; SQL candidate exclusion before LIMIT; '
      'modern preflight, idempotent metadata refusal, active/Started/handled/control preservation; disabled compatibility')
