"""Pinned105 dependency check; no actual DB/network/filesystem. Run with overlay_imports.

Exercises real consumer, handoff, callback and preflight functions with recording
SQL/kernel/transport seams. Actual PostgreSQL acceptance is a separate root gate.
"""
import overlay_imports
from contextlib import ExitStack, contextmanager
from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from functools import partial
import hashlib
import os
from threading import BoundedSemaphore
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from uuid import uuid4
import check_private_workspace_native as fixture
from agent_core.contracts.broker_envelope import PrincipalScope
from agent_core.contracts.session_commands import SessionCommand
from agent_core.domain.events import SessionEvent,EventActor
from agent_core.domain.events import EventType
from agent_core.domain.leases import WorkerLease, LeaseFence
from agent_storage.postgres import command_wakeup_handoff as handoff, command_read_preflight as preflight
from agent_storage.postgres import erp_workspace_policy as policy, erp_private_workspace as facts
from agent_storage.postgres import task_admission
from agent_storage.postgres import coverage_recovery_preparation as coverage
from agent_storage.postgres.command_wakeup import _canonical_json, command_scope_key, _envelope
from agent_storage.postgres.task_io import current_task_io_deadline
from agent_runtime import command_wakeup_consumer as consumer
from zebra_agent_worker import erp_private_preparation as preparation, erp_fresh_authority as fresh

SID, INSTANCE, BINDING, REF = fixture.SID, fixture.INSTANCE, fixture.BINDING, fixture.REF
NOW=datetime.now(UTC); EID,CID=uuid4(),uuid4()
SCOPE=PrincipalScope(kind='principal',tenant_id='erpnext',workspace_id=REF)
ENV={'ZEBRA_ERPNEXT_WORKSPACE_CONTAINMENT':'enabled','ZEBRA_ERPNEXT_PRIVATE_WORKSPACES':'enabled','ZEBRA_ERPNEXT_FRESH_AUTHORITY':'enabled'}
TRACE=[]; CURRENT_MODE='broker'; KIND='message'; BLOCKED=False; RECEIPT=None; RETIRED=False
PENDING=dict(scope_key=command_scope_key(SCOPE),tenant_id='erpnext',workspace_id=REF,session_id=SID,
    accepted_event_id=EID,command_id=CID,current_generation=0,status='pending',origin='live',command_kind=KIND,accepted_sequence=2)
def metadata_event():
    command=SessionCommand(command_id=CID,session_id=SID,kind=KIND,expected_revision=2,idempotency_key='qa',
        payload={'content':'synthetic'} if KIND=='message' else {})
    return SessionEvent.create(session_id=SID,sequence=2,event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,payload=command.event_payload(),created_at=NOW,idempotency_key='qa').model_copy(update={'event_id':EID})
ENVELOPE=_envelope('erpnext',metadata_event(),SCOPE).model_dump(mode='json')
BODY=_canonical_json(ENVELOPE).encode()
OUTBOX=dict(wake_generation=0,envelope_json=ENVELOPE,envelope_digest=hashlib.sha256(BODY).hexdigest(),scope_key=command_scope_key(SCOPE),
    **{k:ENVELOPE[k] for k in ('message_id','message_type','schema_version','aggregate_id','operation_id')})
LEASE=WorkerLease(session_id=SID,fence=LeaseFence(control_plane_epoch=uuid4(),fencing_token=1,owner_instance_id='qa'),
    acquired_at=NOW,heartbeat_at=NOW,expires_at=NOW+timedelta(minutes=1))
class Row:
    def __init__(self,row):self.row=row
    def fetchone(self):return self.row
    def fetchall(self):return []
class Connection:
    def execute(self,sql,args=()):
        if sql.startswith('SET '):return Row(None)
        if 'SELECT mode FROM command_delivery_scope_rollouts' in sql:return Row({'mode':CURRENT_MODE})
        if 'FROM session_command_pending' in sql:return Row(PENDING)
        if 'FROM broker_outbox' in sql:return Row(OUTBOX)
        if 'AS blocked' in sql:
            assert "marker.payload ? 'coverage_admission'" in sql and 'command_coverage_requirements' in sql
            return Row({'blocked':BLOCKED})
        if "payload->>'kind' AS kind" in sql:return Row(dict(session_id=SID,sequence=2,event_type='session_command_accepted',kind=KIND))
        if "jsonb_build_object('payload'" in sql:
            TRACE.append('redacted-metadata')
            row=metadata_event().model_dump();row['payload']=dict(row['payload'],payload={});return Row(row)
        if 'FROM session_projections AS session' in sql:
            return Row(dict(namespace_id='erpnext',task_id=SID,snapshot_json=BINDING.model_dump(mode='json'),binding_digest=BINDING.binding_digest))
        if 'FROM command_retirements' in sql:return Row({'one':1} if RETIRED else None)
        if 'FROM command_handoff_receipts' in sql:return Row(RECEIPT)
        if 'FROM command_recovery_attempts' in sql:return Row(None)
        if 'SELECT payload FROM session_events' in sql:return Row({'payload':{'kind':KIND}})
        if 'SELECT event.event_id FROM session_events AS event' in sql:return Row(None)
        if 'SELECT current_version FROM session_streams' in sql:return Row({'current_version':5})
        if sql.startswith('INSERT INTO command_handoff_receipts'):
            TRACE.append('receipt');return Row(None)
        if 'pg_advisory_xact_lock' in sql:return Row(None)
        raise AssertionError(sql)
    @contextmanager
    def transaction(self):yield
CONNECTION=Connection()
class Database:
    _dsn='qa';deployment_namespace='erpnext'
    @contextmanager
    def connect_task_io(self):yield CONNECTION
DB=Database()
POLICY=NS(_database=DB,_workspace_control=NS(),require=lambda sid:TRACE.append('policy'),
          require_in_transaction=lambda c,sid:None)
def physical(*args,**kw):
    assert current_task_io_deadline() is None
    TRACE.append('physical')
SERVICE=NS(_erp_workspace_containment=POLICY,_workspace_resolver=NS(_private_guard=physical))
def probe(now):
    assert current_task_io_deadline() is None
    TRACE.append('fresh')
    return NS(reason='allowed',require_allowed=lambda:datetime.now(UTC)+timedelta(seconds=30))
FRESH=NS(binding=BINDING,probe=probe)
def checkpoint(*args,**kw):
    assert current_task_io_deadline() is not None
    assert TRACE.index('fresh') < TRACE.index('physical')
    TRACE.append('checkpoint')
def native_prepare(check,*args,**kw):
    assert check is None
    TRACE.append('native-prepare');return None
def acquire(*args,**kw):TRACE.append('lease');return LEASE

def make_consumer(callback):
    value=object.__new__(consumer.CommandWakeupConsumer)
    value._dsn,value._namespace,value._owner='qa','erpnext','qa'
    value._ttl=timedelta(seconds=30);value._coverage_check=Mock()
    value._consumer_capability=None;value._private_preparation=callback
    value._slots=BoundedSemaphore(1);value._execute=Mock();value._execution_finished=Mock()
    value._execution=NS(submit=lambda *a:Future())
    return value

def expect_deferred(callback,*,mode='broker',scope=SCOPE):
    TRACE.clear()
    result=make_consumer(callback)._admit(NS(scope=scope,accepted_event_id=EID),BODY if mode=='broker' else None,mode)
    assert result is consumer.PickupOutcome.DEFERRED
    assert not {'checkpoint','native-prepare','lease','message','receipt'} & set(TRACE),TRACE

with ExitStack() as stack:
    stack.enter_context(patch.dict(os.environ,ENV))
    for module,name,value in ((handoff,'_database',lambda *a:DB),(preflight,'_database',lambda *a:DB),
        (handoff,'_validate',lambda *a:TRACE.append('validate')),(handoff,'_check_inbox',lambda *a:None),
        (handoff,'_terminal_session',lambda *a:False),(handoff,'reject_missing_command_consumer',lambda *a:None),
        (handoff,'pin_command_consumer',lambda *a,**kw:None),(handoff,'lock_session_lease_boundary',lambda *a:None),
        (handoff,'recovery_approval',lambda *a:None),(handoff,'prepare_command_handoff',native_prepare),
        (handoff,'acquire_lease_in_transaction',acquire),(handoff,'_inbox',lambda *a:None),
        (handoff,'read_event_in_transaction',lambda *a:NS()),
        (handoff,'append_command_message',lambda *a,**kw:(TRACE.append('message') or NS(event_id=uuid4(),sequence=6))),
        (preflight,'finish_command_read_state',checkpoint),
        (preflight,'command_event_at',lambda *a:NS(event_type=EventType.SESSION_COMMAND_ACCEPTED,payload={'kind':KIND})),
        (preflight,'command_scope_mode',lambda *a:CURRENT_MODE),
        (policy,'containment_for_database',lambda *a:POLICY),
        (facts,'private_facts',lambda *a:('a'*64,INSTANCE,None)),
        (task_admission,'read_session_task_binding',lambda *a:BINDING)):
        stack.enter_context(patch.object(module,name,value))
    stack.enter_context(patch('agent_storage.postgres.command_rollout.command_scope_mode',lambda *a:CURRENT_MODE))
    stack.enter_context(patch.object(fresh.FreshERPAuthority,'for_execution',return_value=FRESH))
    callback=partial(preparation.prepare_private_command,SERVICE)
    for mode in ('broker','fallback'):
        CURRENT_MODE=mode
        for kind in ('run','resume','message'):
            KIND=kind;PENDING['command_kind']=kind;TRACE.clear()
            result=make_consumer(callback)._admit(NS(scope=SCOPE,accepted_event_id=EID),BODY if mode=='broker' else None,mode)
            assert result is consumer.PickupOutcome.SCHEDULED,(mode,kind,TRACE)
            assert TRACE.index('fresh')<TRACE.index('physical')<TRACE.index('native-prepare')<TRACE.index('lease')<TRACE.index('receipt')
            assert ('checkpoint' in TRACE)==(kind=='message')
            assert TRACE.count('message')==(kind=='message')
        expect_deferred(None,mode=mode)
        with patch.object(FRESH,'probe',return_value=NS(reason='grant_expired')):
            expect_deferred(callback,mode=mode);assert 'physical' not in TRACE
        with patch.object(FRESH,'probe',return_value=NS(reason='probe_rejected')):
            expect_deferred(callback,mode=mode);assert 'physical' not in TRACE
        allowed=NS(reason='allowed',require_allowed=lambda:datetime.now(UTC)+timedelta(seconds=30))
        with patch.object(FRESH,'probe',side_effect=[allowed,NS(reason='probe_rejected')]):
            expect_deferred(callback,mode=mode);assert TRACE.count('physical')==1
        BLOCKED=True
        expect_deferred(callback,mode=mode);assert not {'fresh','physical'} & set(TRACE)
        BLOCKED=False
    CURRENT_MODE='broker'
    # Historical canonical no-effect deliveries settle while Host is unavailable.
    for mode in ('broker','fallback'):
        CURRENT_MODE=mode
        for history in ('handled','retired','accepted'):
            PENDING['status']='done' if history=='handled' else 'pending'
            RETIRED=history=='retired'
            RECEIPT=None if RETIRED else dict(accepted_event_id=EID,session_id=SID,wake_generation=0,status='accepted',handled_event_id=uuid4() if history=='handled' else None)
            TRACE.clear()
            with patch.object(fresh.FreshERPAuthority,'for_execution',side_effect=AssertionError('historical Host probe')):
                result=make_consumer(callback)._admit(NS(scope=SCOPE,accepted_event_id=EID),BODY if mode=='broker' else None,mode)
            assert result is consumer.PickupOutcome.ACKNOWLEDGED,(mode,history,TRACE)
            assert not {'fresh','physical','checkpoint','native-prepare','lease','message','receipt'} & set(TRACE)
        PENDING['status']='pending';RETIRED=False;RECEIPT=None
    CURRENT_MODE='broker';PENDING['current_generation']=1
    TRACE.clear()
    with patch.object(fresh.FreshERPAuthority,'for_execution',side_effect=AssertionError('historical Host probe')):
        result=make_consumer(callback)._admit(NS(scope=SCOPE,accepted_event_id=EID),BODY,'broker')
    assert result is consumer.PickupOutcome.ACKNOWLEDGED
    assert not {'fresh','physical','checkpoint','native-prepare','lease','message','receipt'} & set(TRACE)
    PENDING['current_generation']=0
    # Strict/coverage history remains unsupported; never bypass its native pin via a payload read.
    RECEIPT=dict(accepted_event_id=EID,session_id=SID,wake_generation=0,status='accepted',handled_event_id=uuid4())
    BLOCKED=True;expect_deferred(callback);assert 'fresh' not in TRACE
    BLOCKED=False;RECEIPT=None
    # Native metadata validator rejects tampered raw/outbox without business-content reads.
    original=OUTBOX['envelope_digest'];OUTBOX['envelope_digest']='0'*64
    try:callback('qa','erpnext',SCOPE,EID,BODY,'broker')
    except ValueError:pass
    else:raise AssertionError('tampered historical outbox accepted')
    OUTBOX['envelope_digest']=original
    bad=BODY.replace(ENVELOPE['operation_id'].encode(),str(uuid4()).encode())
    try:callback('qa','erpnext',SCOPE,EID,bad,'broker')
    except ValueError:pass
    else:raise AssertionError('tampered raw accepted')
    # A proof is local to exact current canonical facts and expiry.
    guard=callback('qa','erpnext',SCOPE,EID,BODY,'broker')
    PENDING['command_id']=uuid4()
    try:guard(CONNECTION,'erpnext',EID)
    except coverage.CoverageRecoveryDeferred:pass
    else:raise AssertionError('canonical command mutation accepted')
    PENDING['command_id']=CID
    with patch.object(preparation,'monotonic',return_value=10**20):
        try:guard(CONNECTION,'erpnext',EID)
        except coverage.CoverageRecoveryDeferred:pass
        else:raise AssertionError('expired proof accepted')
    with patch.object(facts,'private_facts',side_effect=ValueError('legacy')):
        TRACE.clear();assert callback('qa','erpnext',SCOPE,EID,BODY,'broker') is None
        assert not {'fresh','physical'} & set(TRACE)
    wrong=PrincipalScope(kind='principal',tenant_id='erpnext',workspace_id='other')
    TRACE.clear()
    try:callback('qa','erpnext',wrong,EID,BODY,'broker')
    except ValueError:pass
    else:raise AssertionError('wrong scope accepted')
    assert not {'fresh','physical','checkpoint','native-prepare','lease'} & set(TRACE)
    # Never call any native coverage prepare implementation in private mode.
    checker=NS(prepare=Mock(side_effect=AssertionError('private coverage bytes')))
    try:coverage.prepare_command_recovery(checker,'erpnext',EID)
    except coverage.CoverageRecoveryDeferred:pass
    else:raise AssertionError('private coverage preparation enabled')
    assert not checker.prepare.called
print('PASS native broker/fallback RUN/RESUME/MESSAGE callback->checkpoint->handoff, missing proof/expired/revoked/coverage/wrong scope zero preparation, exact pins/expiry, legacy no fresh/physical')

# Sibling defenses: classic private commands cannot even load their body; direct
# execution cannot acquire/recover a lease. Modern accepted-lease path above works.
from zebra_agent_worker.command_consumer import SessionCommandConsumer
from zebra_agent_worker.execution_recovery import execute_session_with_lease
from zebra_agent_worker.execution_errors import WorkerExecutionError
with patch.dict(os.environ,ENV):
    private_service=NS(_execution_namespace='erpnext',_erp_workspace_containment=POLICY,
        _claim_service=NS(claim_session=Mock(side_effect=AssertionError('private direct claim'))))
    stores=NS(events=Mock(),sessions=Mock(),workspaces=Mock(),idempotency=Mock())
    reader=Mock(side_effect=AssertionError('private classic body read'))
    classic=SessionCommandConsumer(stores,private_service,
        command_sessions=lambda *a:[NS(session_id=SID,current_sequence=2,status='ready')],next_command=reader)
    result=classic.consume_once(worker_id='qa',lease_ttl_seconds=30)
    assert result.status=='deferred' and result.reason=='erp_private_requires_modern_handoff'
    assert not reader.called and not stores.events.append.called
    try:execute_session_with_lease(private_service,SID,worker_id='qa')
    except WorkerExecutionError as error:assert str(error)=='erp_private_requires_modern_handoff'
    else:raise AssertionError('private direct execution admitted')
    assert not private_service._claim_service.claim_session.called
settings=NS(deployment='cloud',storage_authority='postgresql',command_delivery=NS(consume_enabled=False,scan_fallback_enabled=True))
preparation.require_modern_private_delivery(settings,migrated=True,admission_enabled=True)
for changes,migrated,admission in [({'deployment':'local'},True,True),({'storage_authority':'sqlite'},True,True),({},False,True),({},True,False),({'command_delivery':NS(consume_enabled=False,scan_fallback_enabled=False)},True,True)]:
    invalid=NS(**dict(vars(settings),**changes))
    try:preparation.require_modern_private_delivery(invalid,migrated=migrated,admission_enabled=admission)
    except ValueError:pass
    else:raise AssertionError('private startup accepted non-modern configuration')
print('PASS private classic reader/direct claim never called; modern cloud/migrated/live-admission/active-consumer startup prerequisites')

# Evaluate the actual sweep constructor argument; keep the consumer's exact native
# checker while only private ERP maintenance skips unsupported coverage preparation.
import ast
from pathlib import Path
source=Path(__file__).resolve().parents[1]/'overrides/apps/worker/src/zebra_agent_worker/command_process.py'
tree=ast.parse(source.read_text())
call=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='CommandRecoverySweep')
argument=next(k.value for k in call.keywords if k.arg=='coverage_check')
expression=compile(ast.Expression(argument),str(source),'eval')
checker=NS(prepare=Mock(side_effect=AssertionError('private sweep coverage preparation')))
owner=NS(_namespace='erpnext',_coverage_check=checker)
with patch.dict(os.environ,ENV):
    selected=eval(expression,{'private_activation_enabled':policy.private_activation_enabled,'self':owner})
    assert selected is None and coverage.prepare_command_recovery(selected,'erpnext',EID) is None
    assert not checker.prepare.called
with patch.dict(os.environ,{'ZEBRA_ERPNEXT_PRIVATE_WORKSPACES':'disabled'}):
    assert eval(expression,{'private_activation_enabled':policy.private_activation_enabled,'self':owner}) is checker
    owner._namespace='trench'
    assert eval(expression,{'private_activation_enabled':policy.private_activation_enabled,'self':owner}) is checker
from agent_storage.postgres.command_wakeup_recovery_proof import MAX_GENERATION
assert MAX_GENERATION==5
print('PASS actual sweep wiring skips private coverage prepare, preserves nonERP/disabled native checker and unchanged max-generation5')
