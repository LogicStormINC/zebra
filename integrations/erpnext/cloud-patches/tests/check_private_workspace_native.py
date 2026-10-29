"""Native dependency check: run with pinned105 Worker Python + overlay_imports."""
import overlay_imports
import ast
import inspect
from textwrap import dedent
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from uuid import uuid4
from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef, HostTechnicalLimits
from agent_core.domain.task_bindings import AgentCapabilityCeilingSnapshot, HostCapabilitySnapshot, TaskBindingSnapshot, host_context_digest
from agent_core.domain.workspaces import WorkspaceProjection
from agent_storage.postgres import workspaces as projections
from agent_core.domain.workspace_control import WorkspaceInstance, WorkspaceSource, WorkspaceLifecycleState as State
from agent_runtime.workspace_runtime_resolver import WorkspaceRuntimeResolver
from agent_storage.postgres import erp_private_workspace as native
from agent_storage.postgres import erp_workspace_policy as policy

NOW=datetime.now(UTC); SID=uuid4(); WID=uuid4(); THREAD=str(uuid4()); RUN=str(uuid4()); REF='erp-u-'+'a'*40
CAPS=capability_set(['agent.execute','evidence.read'])
CONTEXT=HostContextEnvelope(grant_id='qa',host_app_id='erpnext',namespace_id='erpnext',workspace_ref=REF,
    resource_refs=tuple(HostResourceRef(type=k,id=v) for k,v in [('thread',THREAD),('principal','qa-a'),('run',RUN)]),
    scopes=('agent.run','erpnext.read'),limits=HostTechnicalLimits(max_runtime_seconds=10,max_model_tokens=10,max_artifact_bytes=10),
    origin='https://erpnext.zebra.local',policy_version='v1',expires_at=NOW+timedelta(minutes=5))
HOST=HostCapabilitySnapshot(host_app_id='erpnext',authority_issuer='https://erpnext.zebra.local',namespace_id='erpnext',
    grant_digest=host_context_digest(CONTEXT),host_context=CONTEXT,connector_id='erp',connector_profile_revision=1,
    connector_profile_digest='c'*64,manifest_digest='d'*64,capabilities=CAPS,resource_binding_digest='e'*64,bound_at=NOW)
BINDING=TaskBindingSnapshot(task_id=str(SID),host_capability=HOST,
    agent_capability_ceiling=AgentCapabilityCeilingSnapshot(definition_snapshot_digest='b'*64,
    capability_profile_ref='profile/default@1',capabilities=CAPS,resolved_at=NOW),
    zebra_policy_digest='f'*64,effective_capabilities=CAPS,binding_revision=1,bound_at=NOW)
INSTANCE=WorkspaceInstance(workspace_id=WID,deployment_namespace='erpnext',
    source=WorkspaceSource(kind='host_reference',locator=f'erpnext://private-workspace/v1/{THREAD}/{REF}'),
    state='pending',quota_bytes=native.QUOTA_BYTES)
WORKSPACE=NS(workspace_root=f'workspace://{WID}')


def refuses(fn):
    try: fn()
    except (ValueError,TypeError,AttributeError): return
    raise AssertionError('expected refusal')


connection=NS(execute=Mock(return_value=NS(fetchone=lambda:{'task_id':SID})))
store=NS(get_in_transaction=Mock(return_value=INSTANCE))
with patch.object(native,'get_workspace_in_transaction',return_value=WORKSPACE), patch.object(native,'read_session_task_binding',return_value=BINDING):
    identity,instance,_=native.private_facts(connection,store,SID,str(WID));assert len(identity)==64
    for changes in [{'quota_bytes':native.QUOTA_BYTES*2},{'state':State.UNCERTAIN},{'owner_session_id':uuid4()},
                    {'source':INSTANCE.source.model_copy(update={'locator':'/old/shared'})}]:
        store.get_in_transaction.return_value=INSTANCE.model_copy(update=changes)
        refuses(lambda:native.private_facts(connection,store,SID,str(WID)))
    store.get_in_transaction.return_value=INSTANCE
    refuses(lambda:native.private_facts(connection,store,SID,str(uuid4())))
    connection.execute.return_value=NS(fetchone=lambda:None)
    refuses(lambda:native.private_facts(connection,store,SID,str(WID)))
    connection.execute.return_value=NS(fetchone=lambda:{'task_id':SID})
    other=CONTEXT.model_copy(update={'workspace_ref':'erp-u-'+'b'*40})
    forged=BINDING.model_copy(update={'host_capability':HOST.model_copy(update={'host_context':other,'grant_digest':host_context_digest(other)})})
    with patch.object(native,'read_session_task_binding',return_value=forged):
        refuses(lambda:native.private_facts(connection,store,SID,str(WID)))

# The default remains a complete native projection, including recovery equality.
full = WorkspaceProjection(session_id=SID, workspace_root=WORKSPACE.workspace_root,
    prepared_at=NOW, updated_at=NOW, current_sequence=1, status='prepared',
    snapshot_path='/private/snapshot', runtime_image='fixture-image')
def full_query(sql, params):
    assert params == ('erpnext', SID)
    if 'FROM workspace_projections' in sql:
        assert 'definition_snapshot' in sql and 'snapshot_path' in sql
        return NS(fetchone=lambda:full.model_dump(mode='python'))
    return NS(fetchone=lambda:{'task_id':SID})
full_connection=NS(execute=Mock(side_effect=full_query))
with patch.object(native,'read_session_task_binding',return_value=BINDING):
    baseline=native.private_facts(full_connection,store,SID,str(WID))
    assert baseline[2] == projections.get_workspace_in_transaction(full_connection,'erpnext',SID) == full
    with patch.dict(os.environ,{'ZEBRA_ERPNEXT_WORKSPACE_CONTAINMENT':'enabled',
            'ZEBRA_ERPNEXT_PRIVATE_WORKSPACES':'enabled','ZEBRA_ERPNEXT_FRESH_AUTHORITY':'enabled'}):
        guard=policy.ERPWorkspaceContainment('unused',deployment_namespace='erpnext',
            workspace_control=NS(deployment_namespace='erpnext',get_in_transaction=store.get_in_transaction))
        guard.require_in_transaction(full_connection,SID,workspace=full)
        for field,value in [('snapshot_path','/different'),('definition_snapshot',{'private_body':'sentinel'})]:
            refuses(lambda:guard.require_in_transaction(full_connection,SID,workspace=full.model_copy(update={field:value})))

# Proof SQL cannot request a definition: reject every query except these two.
root_row=[{'workspace_root':WORKSPACE.workspace_root}]
def metadata_query(sql,params):
    assert params == ('erpnext',SID)
    if sql == ('SELECT workspace_root FROM workspace_projections '
            'WHERE deployment_namespace=%s AND session_id=%s'):
        return NS(fetchone=lambda:root_row[0])
    assert sql == ('SELECT task.task_id FROM agent_tasks task JOIN execution_segments segment '
        'ON segment.deployment_namespace=task.deployment_namespace AND segment.task_id=task.task_id '
        'WHERE task.deployment_namespace=%s AND segment.session_id=%s '
        'AND task.active_segment_id=segment.session_id')
    return NS(fetchone=lambda:{'task_id':SID})
metadata_connection=NS(execute=Mock(side_effect=metadata_query))
with patch.object(native,'get_workspace_in_transaction',side_effect=AssertionError('full workspace read')), \
        patch.object(projections.AgentDefinitionSnapshot,'model_validate',side_effect=AssertionError('private definition read')), \
        patch.object(native,'read_session_task_binding',return_value=BINDING):
    narrowed=native.private_facts(metadata_connection,store,SID,str(WID),metadata_only=True)
    assert narrowed == (baseline[0],baseline[1],None)
    for value in [None,{'workspace_root':None},{'workspace_root':'bad'},
            {'workspace_root':f'workspace://{WID.hex}'},
            {'workspace_root':f'workspace://{uuid4()}'}]:
        root_row[0]=value
        refuses(lambda:native.private_facts(metadata_connection,store,SID,str(WID),metadata_only=True))
    root_row[0]={'workspace_root':WORKSPACE.workspace_root}
    for changes in [{'quota_bytes':native.QUOTA_BYTES*2},{'state':State.UNCERTAIN},
            {'owner_session_id':uuid4()},{'source':INSTANCE.source.model_copy(update={'locator':'/old/shared'})}]:
        store.get_in_transaction.return_value=INSTANCE.model_copy(update=changes)
        refuses(lambda:native.private_facts(metadata_connection,store,SID,str(WID),metadata_only=True))
    store.get_in_transaction.return_value=INSTANCE
    missing=NS(execute=Mock(return_value=NS(fetchone=lambda:None)))
    refuses(lambda:native.private_facts(missing,store,SID,str(WID),metadata_only=True))

# Only the fixed native external proof opts in. Full Worker callers stay default.
proof_ast=ast.parse(inspect.getsource(native.native_workspace_proof))
proof_calls=[n for n in ast.walk(proof_ast) if isinstance(n,ast.Call)
    and isinstance(n.func,ast.Name) and n.func.id=='private_facts']
assert len(proof_calls)==1 and [(kw.arg,ast.literal_eval(kw.value)) for kw in proof_calls[0].keywords]==[('metadata_only',True)]
for source in [inspect.getsource(policy.ERPWorkspaceContainment.require_in_transaction),
        getattr(overlay_imports,'preparation_source',None) or
        (overlay_imports.ROOT/'overrides/apps/worker/src/zebra_agent_worker/erp_private_preparation.py').read_text()]:
    calls=[n for n in ast.walk(ast.parse(dedent(source)))
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='private_facts']
    assert len(calls)==1 and not calls[0].keywords

with tempfile.TemporaryDirectory() as directory:
    ready=INSTANCE.model_copy(update={'state':State.READY,'volume_ref':directory})
    events=[]; current=[INSTANCE]
    def provision(wid):
        events.append('provision');current[0]=ready;return ready
    provisioner=NS(store=NS(get=lambda wid:current[0]),provision_existing=provision)
    def guard(sid,instance,*,allow_allocate):
        events.append('ensure' if allow_allocate else 'verify')
    resolver=WorkspaceRuntimeResolver(provisioner,private_guard=guard)
    assert resolver.resolve(WORKSPACE.workspace_root,session_id=SID)==Path(directory)
    assert events==['ensure','provision','verify']
    events.clear();resolver.resolve_ready(WORKSPACE.workspace_root,session_id=SID);assert events==['verify']
    refuses(lambda:resolver.resolve('/old/shared',session_id=SID))
    events.clear()
    resolver.verify_revision(WORKSPACE.workspace_root, materialized_revision=ready.materialized_revision, session_id=SID)
    assert events == ['verify']
    refuses(lambda:resolver.verify_revision(WORKSPACE.workspace_root, materialized_revision=ready.materialized_revision))
    refuses(lambda:resolver.verify_revision('/old/shared', materialized_revision='r1', session_id=SID))
    events.clear();current[0]=INSTANCE
    def deny(*args,**kwargs):raise ValueError('bad mount')
    resolver=WorkspaceRuntimeResolver(provisioner,private_guard=deny)
    refuses(lambda:resolver.resolve(WORKSPACE.workspace_root,session_id=SID));assert not events
    # Local profile remains byte-compatible without private opt-in.
    assert WorkspaceRuntimeResolver(provisioner).resolve('/old/shared',session_id=SID)==Path('/old/shared')

with patch.dict(os.environ,{'ZEBRA_ERPNEXT_WORKSPACE_CONTAINMENT':'enabled','ZEBRA_ERPNEXT_PRIVATE_WORKSPACES':'enabled','ZEBRA_ERPNEXT_FRESH_AUTHORITY':'enabled'}):
    assert 'source_kind' in policy.eligible_execution_sql('erpnext')
    assert 'p.session_id' in policy.eligible_execution_sql('erpnext',alias='p')
    refuses(lambda:policy.eligible_execution_sql('erpnext',alias='foreign'))
    with patch.dict(os.environ,{'ZEBRA_ERPNEXT_FRESH_AUTHORITY':'disabled'}):
        refuses(lambda:policy.private_activation_enabled('erpnext'))
print('PASS metadata-only root SQL/no full-definition read/default native projection and recovery equality/proof-only opt-in; native private identity/mismatched principal-company-source/unknown lineage/quota/state and resolver allocation-before-provision/continuation/no-mutation failure')
