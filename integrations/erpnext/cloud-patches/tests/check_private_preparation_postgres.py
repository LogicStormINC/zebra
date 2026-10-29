"""Explicit disposable-QA DB flow only; never a production/HTTPS/physical acceptance.

stdin: {"dsn": "...", "expected_database": "zebra_private_workspace_qa_...",
        "allow_qa_writes": true}
Requires an already migrated empty native105/106 QA database. Creates only fixture
Tasks/commands/checkpoints/leases and retains them for root inspection/drop. No
model, business execution, source migration, database creation or cleanup runs.
"""
import overlay_imports
from datetime import UTC, datetime, timedelta
from pathlib import Path
import json
import os
import re
import sys
from types import SimpleNamespace as NS
from unittest.mock import patch
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from psycopg.conninfo import conninfo_to_dict


def main():
    raw=sys.stdin.buffer.read(16385)
    if len(raw)>16384:raise ValueError('bounded QA config required')
    config=json.loads(raw)
    if set(config)!={'dsn','expected_database','allow_qa_writes'} or config['allow_qa_writes'] is not True:
        raise ValueError('explicit QA writes config required')
    name=config['expected_database']
    if not isinstance(name,str) or re.fullmatch(r'zebra_private_workspace_qa_[a-z0-9_]{1,32}',name) is None:
        raise ValueError('dedicated QA database name required')
    dsn=config['dsn']
    if conninfo_to_dict(dsn).get('dbname')!=name:raise ValueError('DSN QA database mismatch')
    with psycopg.connect(dsn,row_factory=dict_row) as connection:
        if connection.execute('SELECT current_database() AS name').fetchone()['name']!=name:
            raise ValueError('connected QA database mismatch')
        if connection.execute('SELECT count(*) AS n FROM agent_tasks').fetchone()['n']:
            raise ValueError('QA database must have no existing Tasks')
        version=connection.execute('SELECT max(version) AS v FROM zebra_schema_migrations').fetchone()['v']
        if version not in {105,106}:raise ValueError('exact105/106 migrated QA database required')
    # Guard has passed before any write/import-side test fixture work.
    from agent_core.application.session_bootstrap import SessionBootstrapCommand,SessionBootstrapService
    from agent_core.application.workspace_projection import rebuild_workspace
    from agent_core.application.session_projection import rebuild_session
    from agent_core.domain.turns import derive_turn_id,InteractionMode
    from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
    from agent_storage.postgres.events import PostgresEventStore
    from agent_storage.postgres.leases import PostgresLeaseStore
    from agent_storage.postgres.projections import PostgresProjectionStore
    from agent_storage.postgres.workspaces import PostgresWorkspaceProjectionStore
    from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore
    from agent_core.contracts.session_commands import SessionCommand
    from agent_core.contracts.broker_envelope import PrincipalScope
    from agent_core.domain.events import SessionEvent,EventActor,EventType
    from agent_core.domain.host_authority import HostResourceRef
    from agent_core.domain.task_bindings import host_context_digest
    from agent_core.domain.workspace_control import WorkspaceSource
    from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.workspace_control import PostgresWorkspaceControlStore
    from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
    from agent_storage.postgres.erp_workspace_policy import ERPWorkspaceContainment
    from agent_storage.postgres.command_rollout import set_command_scope_rollout
    from agent_storage.postgres.command_wakeup import command_scope_key,_canonical_json
    from agent_storage.postgres.command_wakeup_handoff import handoff_command,HandoffStatus
    from agent_storage.postgres.coverage_recovery_preparation import CoverageRecoveryDeferred
    from agent_storage.postgres.task_io import current_task_io_deadline
    from zebra_agent_worker.erp_private_preparation import prepare_private_command
    from zebra_agent_worker.erp_fresh_authority import FreshERPAuthority
    import check_private_workspace_native as fixture

    namespace='erpnext';database=PostgresDatabase(dsn,deployment_namespace=namespace)
    store=PostgresWorkspaceControlStore(dsn,deployment_namespace=namespace)
    policy=ERPWorkspaceContainment(dsn,deployment_namespace=namespace,workspace_control=store)
    events=PostgresEventStore(dsn,deployment_namespace=namespace)
    sessions=PostgresProjectionStore(dsn,deployment_namespace=namespace)
    workspaces=PostgresWorkspaceProjectionStore(dsn,deployment_namespace=namespace)
    tasks=PostgresAgentTaskStore(dsn,deployment_namespace=namespace)
    leases=PostgresLeaseStore(dsn,deployment_namespace=namespace)
    def worker_event(lease,kind,payload):
        # Synthetic prior-turn fixture only, through the actual fenced native writer.
        prior=events.list_for_session(lease.session_id)
        sessions.save_session(rebuild_session(prior));workspaces.save_workspace(rebuild_workspace(prior))
        event=SessionEvent.create(session_id=lease.session_id,sequence=prior[-1].sequence+1,
            event_type=kind,actor=EventActor.HARNESS,payload=payload)
        stream=[*prior,event]
        workspaces.commit_worker_event(event,rebuild_session(stream),rebuild_workspace(stream),
            authority=WorkerMutationAuthority(deployment_namespace=namespace,session_id=lease.session_id,
                expected_stream_revision=prior[-1].sequence,lease_fence=lease.fence))
        tasks.ensure_for_session(lease.session_id)
        return event
    with database.connect() as connection:
        connection.execute('INSERT INTO command_wakeup_rollouts (deployment_namespace,admission_enabled) VALUES (%s,true)',(namespace,))

    def create(mode,kind):
        now=datetime.now(UTC);wid,thread=uuid4(),str(uuid4());ref='erp-u-'+uuid4().hex+uuid4().hex[:8]
        context=fixture.CONTEXT.model_copy(update=dict(workspace_ref=ref,expires_at=now+timedelta(minutes=10),resource_refs=(
            HostResourceRef(type='thread',id=thread),HostResourceRef(type='principal',id='qa-user'),HostResourceRef(type='run',id=str(uuid4())))))
        host=fixture.HOST.model_copy(update=dict(host_context=context,grant_digest=host_context_digest(context),grant_expires_at=context.expires_at))
        boot=SessionBootstrapService().build(SessionBootstrapCommand(title='private QA '+kind,user_input='synthetic QA input',
            workspace_root=Path('workspace://'+str(wid)),host_context=context,created_at=now,interaction_mode=InteractionMode.CONVERSATION))
        sid=boot.session.session_id
        binding=fixture.BINDING.model_copy(update=dict(task_id=str(sid),host_capability=host,bound_at=now))
        store.create_pending(WorkspaceSource(kind='host_reference',locator=f'erpnext://private-workspace/v1/{thread}/{ref}'),
            workspace_id=wid,quota_bytes=256*1024*1024,owner_session_id=None,idempotency_key=str(wid))
        if kind=='message':
            PostgresTaskAdmissionTransaction(dsn,deployment_namespace=namespace).admit(TaskAdmissionRequest(
                events=boot.events,session=boot.session,workspace=rebuild_workspace(list(boot.events)),binding=binding))
            fixture_lease=leases.acquire(sid,owner_instance_id='qa-synthetic-prior-turn',ttl=timedelta(seconds=30))
            worker_event(fixture_lease,EventType.HARNESS_ATTEMPT_STARTED,{'attempt_number':1})
            completed=worker_event(fixture_lease,EventType.TURN_COMPLETED,dict(turn_id=str(derive_turn_id(sid,0)),
                turn_index=0,summary='synthetic disposable QA prior turn; no model executed',closes_segment=False))
            leases.release(sid,fence=fixture_lease.fence)
            revision=completed.sequence
        else:
            revision=2
        command=SessionCommand(session_id=sid,kind=kind,expected_revision=revision,idempotency_key=str(uuid4()),
            payload={'content':'synthetic QA message'} if kind=='message' else {
                'thread_id':str(sid),'run_id':next(r.resource_id for r in context.resource_refs if r.resource_type=='run'),
                'input':{'messages':[]}})
        accepted=SessionEvent.create(session_id=sid,sequence=revision+1,event_type=EventType.SESSION_COMMAND_ACCEPTED,actor=EventActor.USER,
            payload=command.event_payload(),created_at=now,idempotency_key=command.idempotency_key)
        if kind=='message':
            events.append(accepted);tasks.ensure_for_session(sid)
        else:
            PostgresTaskAdmissionTransaction(dsn,deployment_namespace=namespace).admit(TaskAdmissionRequest(
                events=boot.events+(accepted,),session=boot.session,workspace=rebuild_workspace(list(boot.events)),binding=binding))
        scope=PrincipalScope(kind='principal',tenant_id=namespace,workspace_id=ref)
        if mode=='broker':set_command_scope_rollout(dsn,deployment_namespace=namespace,scope_key=command_scope_key(scope),mode='broker',actor='qa',reason='disposable private preparation fixture')
        with database.connect_task_io() as connection:
            row=connection.execute('SELECT envelope_json FROM broker_outbox WHERE deployment_namespace=%s AND operation_id=%s',(namespace,command.command_id)).fetchone()
            assert row is not None
            body=_canonical_json(row['envelope_json']).encode() if mode=='broker' else None
        return sid,binding,accepted,scope,body

    def snapshot(sid,aid):
        with database.connect_task_io() as connection:
            return dict(heads=connection.execute('SELECT count(*) AS n FROM session_command_read_heads WHERE deployment_namespace=%s AND session_id=%s',(namespace,sid)).fetchone()['n'],
                receipt=connection.execute('SELECT count(*) AS n FROM command_handoff_receipts WHERE deployment_namespace=%s AND accepted_event_id=%s',(namespace,aid)).fetchone()['n'],
                messages=connection.execute("SELECT count(*) AS n FROM session_events WHERE deployment_namespace=%s AND session_id=%s AND event_type='user_message_received'",(namespace,sid)).fetchone()['n'])
    records=[]
    env={'ZEBRA_ERPNEXT_WORKSPACE_CONTAINMENT':'enabled','ZEBRA_ERPNEXT_PRIVATE_WORKSPACES':'enabled','ZEBRA_ERPNEXT_FRESH_AUTHORITY':'enabled'}
    with patch.dict(os.environ,env):
        for mode in ('broker','fallback'):
            for kind in ('run','resume','message'):
                sid,binding,accepted,scope,body=create(mode,kind);calls=[]
                def probe(now):
                    assert current_task_io_deadline() is None
                    calls.append('fresh');return NS(reason='allowed',require_allowed=lambda:datetime.now(UTC)+timedelta(seconds=30))
                def physical(*a,**kw):
                    assert current_task_io_deadline() is None
                    calls.append('physical')
                service=NS(_erp_workspace_containment=policy,_workspace_resolver=NS(_private_guard=physical))
                fresh=NS(binding=binding,probe=probe)
                with patch.object(FreshERPAuthority,'for_execution',return_value=fresh):
                    for attempt in range(3):
                        guard=prepare_private_command(service,dsn,namespace,scope,accepted.event_id,body,mode)
                        assert callable(guard) and calls[-3:]==['fresh','physical','fresh']
                        result=handoff_command(dsn,deployment_namespace=namespace,scope=scope,accepted_event_id=accepted.event_id,
                            owner_instance_id='private-qa',ttl=timedelta(seconds=30),raw_body=body,required_scope_mode=mode,private_preparation=guard)
                        if result.status is not HandoffStatus.PREPARING:break
                    assert result.status is HandoffStatus.ACCEPTED,(mode,kind,result.status)
                    assert result.lease is not None and result.lease.session_id==sid
                    state=snapshot(sid,accepted.event_id)
                    assert state['receipt']==1 and state['messages']==(2 if kind=='message' else 1),state
                    guard=prepare_private_command(service,dsn,namespace,scope,accepted.event_id,body,mode)
                    again=handoff_command(dsn,deployment_namespace=namespace,scope=scope,accepted_event_id=accepted.event_id,
                        owner_instance_id='private-qa',ttl=timedelta(seconds=30),raw_body=body,required_scope_mode=mode,private_preparation=guard)
                    assert again.status is HandoffStatus.DUPLICATE
                    assert snapshot(sid,accepted.event_id)['messages']==state['messages']
                # Actual historical handled receipt, not a manually patched row:
                # close this synthetic accepted Turn through native fenced writes.
                worker_event(result.lease,EventType.HARNESS_ATTEMPT_STARTED,{'attempt_number':1})
                worker_event(result.lease,EventType.TURN_COMPLETED,dict(turn_id=str(derive_turn_id(sid,1 if kind=='message' else 0)),
                    turn_index=1 if kind=='message' else 0,summary='synthetic disposable QA handled Turn; no model executed',closes_segment=False))
                leases.release(sid,fence=result.lease.fence)
                before_history=snapshot(sid,accepted.event_id)
                def forbidden(*args,**kwargs):raise AssertionError('historical no-effect delivery called fresh/physical work')
                service._workspace_resolver._private_guard=forbidden
                fresh.probe=forbidden
                with patch.object(FreshERPAuthority,'for_execution',side_effect=forbidden):
                    guard=prepare_private_command(service,dsn,namespace,scope,accepted.event_id,body,mode)
                    assert guard is None
                    historical=handoff_command(dsn,deployment_namespace=namespace,scope=scope,accepted_event_id=accepted.event_id,
                        owner_instance_id='private-qa',ttl=timedelta(seconds=30),raw_body=body,required_scope_mode=mode,private_preparation=guard)
                assert historical.status is HandoffStatus.DUPLICATE
                assert snapshot(sid,accepted.event_id)==before_history
                with database.connect_task_io() as connection:
                    receipt=connection.execute('SELECT started_event_id,handled_event_id FROM command_handoff_receipts WHERE deployment_namespace=%s AND accepted_event_id=%s',
                        (namespace,accepted.event_id)).fetchone()
                    assert receipt['started_event_id'] is not None and receipt['handled_event_id'] is not None
                records.append(dict(mode=mode,kind=kind,accepted=True,message_count=state['messages'],historical_handled_no_fresh_physical=True))
            # Negative pre-lease outcomes retain the same canonical pending command.
            for failure in ('missing','expired','revoked'):
                sid,binding,accepted,scope,body=create(mode,'message');before=snapshot(sid,accepted.event_id)
                service=NS(_erp_workspace_containment=policy,_workspace_resolver=NS(_private_guard=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('denied physical work'))))
                fresh=NS(binding=binding,probe=lambda now:NS(reason='grant_expired' if failure=='expired' else 'probe_rejected'))
                try:
                    with patch.object(FreshERPAuthority,'for_execution',return_value=fresh):
                        guard=None if failure=='missing' else prepare_private_command(service,dsn,namespace,scope,accepted.event_id,body,mode)
                        handoff_command(dsn,deployment_namespace=namespace,scope=scope,accepted_event_id=accepted.event_id,owner_instance_id='private-qa',
                            ttl=timedelta(seconds=30),raw_body=body,required_scope_mode=mode,private_preparation=guard)
                except CoverageRecoveryDeferred:pass
                else:raise AssertionError('denied preparation accepted')
                assert snapshot(sid,accepted.event_id)==before
                with database.connect_task_io() as connection:
                    row=connection.execute('SELECT status FROM session_command_pending WHERE deployment_namespace=%s AND accepted_event_id=%s',(namespace,accepted.event_id)).fetchone()
                    assert row['status']=='pending'
                records.append(dict(mode=mode,failure=failure,pending_retained=True,no_preparation=True))
        # Real known-unavailable recovery: same immutable command, generations0..5,
        # no Started/business input/model. Select the actual sweep argument expression.
        import ast
        from agent_storage.postgres.erp_workspace_policy import private_activation_enabled
        from agent_storage.postgres.command_wakeup_recovery import _recover,RecoveryStatus
        from agent_storage.postgres import erp_fresh_disposition as disposition
        tree=ast.parse((Path(__file__).resolve().parents[1]/'overrides/apps/worker/src/zebra_agent_worker/command_process.py').read_text())
        sweep=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='CommandRecoverySweep')
        argument=next(k.value for k in sweep.keywords if k.arg=='coverage_check')
        def no_coverage(*a,**kw):raise AssertionError('private recovery entered unsupported coverage prepare')
        owner=NS(_namespace=namespace,_coverage_check=NS(prepare=no_coverage))
        selected=eval(compile(ast.Expression(argument),'<actual-sweep-argument>','eval'),{'self':owner,'private_activation_enabled':private_activation_enabled})
        assert selected is None
        sid,binding,accepted,scope,body=create('broker','run');old_body=body
        def allowed(now):return NS(reason='allowed',require_allowed=lambda:datetime.now(UTC)+timedelta(seconds=30))
        service=NS(_erp_workspace_containment=policy,_workspace_resolver=NS(_private_guard=lambda *a,**kw:None))
        fresh=NS(binding=binding,probe=allowed)
        for generation in range(6):
            with patch.object(FreshERPAuthority,'for_execution',return_value=fresh):
                guard=prepare_private_command(service,dsn,namespace,scope,accepted.event_id,body,'broker')
                picked=handoff_command(dsn,deployment_namespace=namespace,scope=scope,accepted_event_id=accepted.event_id,
                    owner_instance_id='private-qa-recovery',ttl=timedelta(seconds=30),raw_body=body,required_scope_mode='broker',private_preparation=guard)
            assert picked.status is HandoffStatus.ACCEPTED,(generation,picked.status)
            disposition.persist_fresh_disposition(dsn,namespace,picked.lease,
                code=disposition.UNAVAILABLE,reason='probe_timeout')
            leases.release(sid,fence=picked.lease.fence)
            with database.connect() as connection:
                # Explicit clock advancement only for this owned disposable fixture.
                connection.execute("UPDATE worker_leases SET acquired_at=clock_timestamp()-interval '3 minutes',heartbeat_at=clock_timestamp()-interval '2 minutes',expires_at=clock_timestamp()-interval '1 minute' WHERE deployment_namespace=%s AND session_id=%s",(namespace,sid))
                connection.execute("UPDATE session_command_pending SET recovery_due_at=clock_timestamp()-interval '1 second' WHERE deployment_namespace=%s AND accepted_event_id=%s",(namespace,accepted.event_id))
                recovered=_recover(connection,namespace,scope,{'accepted_event_id':accepted.event_id,'session_id':sid},coverage_check=selected)
            if generation==5:
                assert recovered.status is RecoveryStatus.EXHAUSTED
                break
            assert recovered.status is RecoveryStatus.APPROVED and recovered.generation==generation+1
            # A stale broker delivery settles from metadata while Host is unavailable.
            def forbidden(*a,**kw):raise AssertionError('stale generation entered cold authority work')
            with patch.object(FreshERPAuthority,'for_execution',side_effect=forbidden):
                stale_guard=prepare_private_command(service,dsn,namespace,scope,accepted.event_id,old_body,'broker')
                assert stale_guard is None
                stale=handoff_command(dsn,deployment_namespace=namespace,scope=scope,accepted_event_id=accepted.event_id,
                    owner_instance_id='private-qa-recovery',ttl=timedelta(seconds=30),raw_body=old_body,required_scope_mode='broker',private_preparation=stale_guard)
                assert stale.status is HandoffStatus.DUPLICATE
            with database.connect_task_io() as connection:
                row=connection.execute('SELECT envelope_json FROM broker_outbox WHERE deployment_namespace=%s AND operation_id=%s AND wake_generation=%s',
                    (namespace,json.loads(old_body)['operation_id'],generation+1)).fetchone()
                body=_canonical_json(row['envelope_json']).encode()
        with database.connect_task_io() as connection:
            assert disposition.verified_fresh_disposition(connection,namespace,accepted.event_id,terminal=True) is not None
            assert connection.execute("SELECT count(*) AS n FROM session_events WHERE deployment_namespace=%s AND session_id=%s AND event_type='harness_attempt_started'",(namespace,sid)).fetchone()['n']==0
        assert snapshot(sid,accepted.event_id)['messages']==1
        records.append(dict(private_sweep_checker_none=True,known_unavailable_generations=list(range(6)),exhausted=True,no_started_or_business_replay=True,stale_delivery_no_fresh_physical=True))
    print(json.dumps(dict(proof='disposable QA PostgreSQL checkpoint/handoff only; synthetic fresh/physical seams',database=name,cases=records),sort_keys=True))

if __name__=='__main__':main()
