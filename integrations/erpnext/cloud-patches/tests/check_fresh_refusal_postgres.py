"""Disposable native105 PG only; no migration, broker, Host, model or business IO.

Root supplies ZEBRA_FRESH_REFUSAL_QA_DSN on the isolated QA network. The check
refuses any database outside the two explicitly owned QA databases.
"""
import overlay_imports
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from psycopg.types.json import Jsonb
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.contracts.broker_envelope import PrincipalScope
from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef, HostTechnicalLimits
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.task_bindings import AgentCapabilityCeilingSnapshot, HostCapabilitySnapshot, TaskBindingSnapshot, host_context_digest
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_storage import bootstrap_control_plane_epoch
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from agent_storage.postgres.leases import PostgresLeaseStore
from agent_storage.postgres.command_wakeup_discovery import begin_command_backfill
from agent_storage.postgres.command_wakeup_handoff import handoff_command, HandoffStatus
from agent_storage.postgres.command_wakeup_recovery import _recover, RecoveryStatus
from agent_storage.postgres import erp_fresh_disposition as disposition

DSN = os.environ['ZEBRA_FRESH_REFUSAL_QA_DSN']
NS = 'erpnext'
db = PostgresDatabase(DSN, deployment_namespace=NS)
with db.connect() as c:
    qa_schemas={'erpnext_fresh_refusal_20261024':105,'erpnext_fresh_refusal_106_20261024':106}
    database_name=c.execute('SELECT current_database() AS name').fetchone()['name']
    assert database_name in qa_schemas
    assert c.execute('SELECT max(version) AS n FROM zebra_schema_migrations').fetchone()['n']==qa_schemas[database_name]
with db.connect() as c:
    existing_epoch = c.execute('SELECT epoch FROM control_plane_epochs WHERE deployment_namespace=%s', (NS,)).fetchone()
if existing_epoch is None:
    bootstrap_control_plane_epoch(DSN, deployment_namespace=NS)
else:
    assert existing_epoch['epoch'] is not None  # Preserve existing disposable authority; never rotate it.
events = PostgresEventStore(DSN, deployment_namespace=NS)
leases = PostgresLeaseStore(DSN, deployment_namespace=NS)
CAPS=capability_set(['agent.execute','evidence.read'])

def setup(*, coverage=None, configuration_digest=None, host_expiry=None):
    now=datetime.now(UTC); run=str(uuid4())
    context=HostContextEnvelope(grant_id=str(uuid4()),host_app_id=NS,namespace_id=NS,
        workspace_ref='fresh-check-'+str(uuid4()), resource_refs=tuple(HostResourceRef(type=k,id=v) for k,v in
          [('thread','host-thread'),('principal','qa-owner'),('run',run)]+([] if coverage is None else [('trench.history',coverage.history_ref)])),
        scopes=('agent.run','erpnext.read')+(() if coverage is None else ('history.read','history.snapshot.write')),
        limits=HostTechnicalLimits(max_runtime_seconds=600,max_model_tokens=1000,max_artifact_bytes=1000),
        origin='https://erp.example.test',policy_version='v1',expires_at=host_expiry or now+timedelta(minutes=30))
    boot=SessionBootstrapService().build(SessionBootstrapCommand(title='fresh-refusal-qa',user_input='original private request',
        workspace_root=Path('/tmp/fresh-refusal-qa'),host_context=context,coverage_admission=coverage))
    sid=boot.session.session_id
    bound=TaskBindingSnapshot(task_id=str(sid),agent_capability_ceiling=AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest='b'*64,capability_profile_ref='test/default@1',capabilities=CAPS,resolved_at=now),
        host_capability=HostCapabilitySnapshot(host_app_id=NS,authority_issuer='https://erp.example.test',namespace_id=NS,
          host_context=context,grant_digest=host_context_digest(context),grant_expires_at=context.expires_at,
          connector_id='erp',connector_profile_revision=1,connector_profile_digest='c'*64,manifest_digest='d'*64,
          capabilities=CAPS,resource_binding_digest='e'*64,bound_at=now),
        zebra_policy_digest='f'*64,effective_capabilities=CAPS,binding_revision=1,bound_at=now)
    command=SessionCommand(command_id=uuid4(),session_id=sid,kind=SessionCommandKind.RUN,expected_revision=2,
        idempotency_key=str(uuid4()),payload={'thread_id':str(sid),'run_id':run,'input':{'messages':[]}})
    event=SessionEvent.create(session_id=sid,sequence=3,event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,payload=command.event_payload(),idempotency_key=command.idempotency_key)
    request=TaskAdmissionRequest(events=(*boot.events,event),session=boot.session,
        workspace=rebuild_workspace(list(boot.events)),binding=bound)
    if coverage is None:
        PostgresTaskAdmissionTransaction(DSN,deployment_namespace=NS).admit(request)
    else:
        from agent_storage.postgres.command_coverage_admission import admit_coverage_task
        admit_coverage_task(DSN,NS,request,configuration_digest)
    return sid,event,PrincipalScope(kind='principal',tenant_id=NS,workspace_id=context.workspace_ref)

def rejected(action):
    try: action()
    except (ValueError, LeaseLostError): return
    raise AssertionError('expected no-effect proof refusal')

def seal(lease,event=None,code=disposition.REFUSED):
    return disposition.persist_fresh_disposition(DSN,NS,lease,accepted_event=event,code=code,
        reason='probe_timeout' if code==disposition.UNAVAILABLE else 'probe_rejected')

def read(event,terminal=False):
    with db.connect() as c:
        return disposition.verified_fresh_disposition(c,NS,event.event_id,terminal=terminal)

# Classic uses exact canonical fingerprint and immutable rejection, no pending row.
with db.connect() as c:
    c.execute('UPDATE command_wakeup_rollouts SET admission_enabled=false WHERE deployment_namespace=%s',(NS,))
sid,classic,scope=setup();lease=leases.acquire(sid,owner_instance_id='qa-classic',ttl=timedelta(seconds=60))
body=seal(lease,classic)
assert body==seal(lease,classic) and read(classic,True)==body
assert 'original private request' not in str(body) and 'payload' not in body
leases.release(sid,fence=lease.fence)
with db.connect() as c:
    assert disposition.fresh_retry_eligible(c,NS,body)
    assert c.execute("SELECT count(*) AS n FROM session_events WHERE deployment_namespace=%s AND session_id=%s",(NS,sid)).fetchone()['n']==4
print('PASS PG classic exact receipt, immutable replay, retained canonical history and released lease')

# Native operator enablement on this disposable namespace; use real handoff.
with db.connect() as c:
    c.execute("INSERT INTO command_wakeup_rollouts(deployment_namespace,admission_enabled) VALUES(%s,true) ON CONFLICT(deployment_namespace) DO UPDATE SET admission_enabled=true",(NS,))

def accepted():
    sid,event,scope=setup()
    handoff=handoff_command(DSN,deployment_namespace=NS,scope=scope,accepted_event_id=event.event_id,
        owner_instance_id='qa-modern-'+str(uuid4()),ttl=timedelta(seconds=60))
    assert handoff.status is HandoffStatus.ACCEPTED
    return sid,event,scope,handoff.lease

sid,event,scope,lease=accepted()
with ThreadPoolExecutor(max_workers=2) as pool:
    proofs=list(pool.map(lambda _:seal(lease),range(2)))
assert proofs[0]==proofs[1]==read(event,True)
with db.connect() as c:
    row=c.execute('SELECT * FROM command_handoff_receipts WHERE deployment_namespace=%s AND accepted_event_id=%s',(NS,event.event_id)).fetchone()
    assert row['started_event_id'] is row['handled_event_id'] is None
    assert c.execute("SELECT count(*) AS n FROM session_events WHERE deployment_namespace=%s AND session_id=%s",(NS,sid)).fetchone()['n']==4
leases.release(sid,fence=lease.fence)
print('PASS PG modern native handoff/fence/Inbox proof, concurrent idempotent writers, no execution events')

# Late actual fence assertion failure rolls back both tentative journal and pending.
sid,late,scope,lease=accepted()
original=disposition.assert_current_lease_fence; count=0

def expire(*args):
    global count
    count+=1
    if count==2: raise LeaseLostError('late QA fence loss')
    return original(*args)
with patch.object(disposition,'assert_current_lease_fence',expire): rejected(lambda:seal(lease))
with db.connect() as c:
    assert c.execute('SELECT 1 FROM control_plane_idempotency_records WHERE deployment_namespace=%s AND action=%s AND idempotency_key=%s',(NS,disposition.ACTION,f'{late.event_id}:0')).fetchone() is None
    assert c.execute('SELECT status FROM session_command_pending WHERE deployment_namespace=%s AND accepted_event_id=%s',(NS,late.event_id)).fetchone()['status']=='pending'
leases.release(sid,fence=lease.fence)
print('PASS PG late fence failure atomic rollback (injected at final native assertion)')

# Real generation approvals preserve known unavailability without start/handled fiction.
sid,temporary,scope,lease=accepted()
for generation in range(6):
    seal(lease,code=disposition.UNAVAILABLE)
    leases.release(sid,fence=lease.fence)
    with db.connect() as c:
        # Disposable clock advancement, leaving the exact released fence intact.
        c.execute("UPDATE worker_leases SET acquired_at=clock_timestamp()-interval '3 minutes',heartbeat_at=clock_timestamp()-interval '2 minutes',expires_at=clock_timestamp()-interval '1 minute' WHERE deployment_namespace=%s AND session_id=%s",(NS,sid))
        c.execute("UPDATE session_command_pending SET recovery_due_at=clock_timestamp()-interval '1 second' WHERE deployment_namespace=%s AND accepted_event_id=%s",(NS,temporary.event_id))
        result=_recover(c,NS,scope,{'accepted_event_id':temporary.event_id,'session_id':sid})
    if generation==5:
        assert result.status is RecoveryStatus.EXHAUSTED and read(temporary,True) is not None
        break
    assert result.status is RecoveryStatus.APPROVED and result.generation==generation+1
    with db.connect() as c:
        audit=c.execute('SELECT previous_receipt FROM command_recovery_attempts WHERE deployment_namespace=%s AND accepted_event_id=%s AND wake_generation=%s',(NS,temporary.event_id,generation+1)).fetchone()['previous_receipt']
        assert audit['early_authority_code']==disposition.UNAVAILABLE and audit['started_event_id'] is None
    picked=handoff_command(DSN,deployment_namespace=NS,scope=scope,accepted_event_id=temporary.event_id,
        owner_instance_id='qa-recovery-'+str(generation),ttl=timedelta(seconds=60))
    assert picked.status is HandoffStatus.ACCEPTED
    lease=picked.lease
print('PASS PG native generation ceiling 5 (0..5), unavailable audit, exhausted no-execution proof')
