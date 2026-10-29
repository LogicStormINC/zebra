"""Run on pinned105 + overlay_imports; no database, real model or external network."""
import overlay_imports
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import inspect
import json
import os
from pathlib import Path
from threading import RLock
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx
from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.execution_authority import ExecutionAuthorityResolutionRequest, ExecutionAuthorityResolutionError, ExecutionAuthorityRevalidation
from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef, HostTechnicalLimits
from agent_core.domain.host_connectors import HostConnectorProfileVersion, HostConnectorBinding
from agent_core.domain.task_bindings import AgentCapabilityCeilingSnapshot, HostCapabilitySnapshot, TaskBindingSnapshot, host_context_digest
from agent_core.domain.tools import ToolCall
from agent_integrations.host_credentials import ConfiguredHmacHostCredentialResolver
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway
from zebra_agent_worker import erp_fresh_authority as fresh
from zebra_agent_worker.bound_execution_authority import BoundHostExecutionAuthorityResolver, select_attempt_authority
from zebra_agent_worker.worker_tool_gateway import WorkerToolGateway

NOW = datetime.now(UTC)
SID, TASK, RUN = uuid4(), str(uuid4()), str(uuid4())
PROFILE = HostConnectorProfileVersion(host_app_id='erpnext', connector_id='erp', profile_revision=1,
    base_uri='https://erp.example.test', manifest_path='/manifest', invoke_path_template='/tools',
    supported_protocol_versions=('v1',), workload_identity_ref='erpnext-worker', credential_ref='erp/workload')
PROFILE_BINDING = HostConnectorBinding(host_app_id='erpnext', namespace_id='erpnext', connector_id='erp', profile_revision=1,
    binding_revision=1)
REGISTRY = NS(resolve_binding=lambda *a: PROFILE_BINDING, get_profile=lambda *a: PROFILE)
CAPS = capability_set(['agent.execute', 'evidence.read'])
CONTEXT = HostContextEnvelope(grant_id='check-only-grant', host_app_id='erpnext', namespace_id='erpnext',
    workspace_ref='erp-u-'+'a'*40, resource_refs=tuple(HostResourceRef(type=k,id=v) for k,v in (
        ('thread','host-thread'),('principal','qa-user'),('run',RUN))),
    scopes=('agent.run','erpnext.read'), limits=HostTechnicalLimits(max_runtime_seconds=600,max_model_tokens=40000,max_artifact_bytes=1000),
    origin='https://erp.example.test', policy_version='erpnext-v1', expires_at=NOW+timedelta(minutes=10))
HOST = HostCapabilitySnapshot(host_app_id='erpnext', authority_issuer='https://erp.example.test', namespace_id='erpnext',
    grant_digest=host_context_digest(CONTEXT), host_context=CONTEXT, grant_expires_at=CONTEXT.expires_at,
    connector_id='erp', connector_profile_revision=1, connector_profile_digest=PROFILE.profile_digest,
    manifest_digest='a'*64, capabilities=CAPS,resource_binding_digest='b'*64,bound_at=NOW)
BINDING = TaskBindingSnapshot(task_id=TASK, agent_capability_ceiling=AgentCapabilityCeilingSnapshot(
    definition_snapshot_digest='c'*64, capability_profile_ref='test/default@1',capabilities=CAPS,resolved_at=NOW),
    host_capability=HOST,zebra_policy_digest='d'*64,effective_capabilities=CAPS,binding_revision=1,bound_at=NOW)
CREDENTIAL = ConfiguredHmacHostCredentialResolver('test-only-hmac')


class Host:
    def __init__(self): self.mode, self.calls = 'allow', []
    def __call__(self, request):
        body=json.loads(request.content); self.calls.append(body)
        assert request.url.path=='/tools/erpnext.authority/invoke'
        assert body['toolName']=='erpnext.authority' and set(body['arguments'])==set(fresh._ARGUMENTS)
        canonical='\n'.join(['POST',request.url.path,CONTEXT.grant_id,CONTEXT.workspace_ref,'erpnext','erpnext',
                              json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':'))])
        assert hmac.compare_digest(request.headers['X-Zebra-Host-Auth'], hmac.new(b'test-only-hmac',canonical.encode(),hashlib.sha256).hexdigest())
        assert request.headers['X-Zebra-Workload-Identity']=='erpnext-worker'
        if self.mode=='timeout': raise httpx.ReadTimeout('test timeout')
        if self.mode=='revoke': return httpx.Response(403,json={'error':'permission revoked'})
        if self.mode=='malformed': return httpx.Response(200,json={'output':'{"decision": "allowed"}'})
        identity={key:value for key,value in body['arguments'].items() if key!='expires_at'}|{'company':'QA Company'}
        if self.mode=='drift': identity['run_id']='different-run'
        expiry=CONTEXT.expires_at
        if self.mode=='expand': expiry+=timedelta(seconds=1)
        if self.mode=='expired': expiry=NOW-timedelta(seconds=1)
        result=dict(decision='allowed',identity=identity,
                    metadata_digest=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                    expires_at=expiry.isoformat())
        return httpx.Response(200,json={'output':json.dumps(result)})


class Recorder:
    def __init__(self, snapshot):
        self.lock=RLock(); self.session=NS(session_id=SID); self.events=[]; self.active=True
        self.snapshot=snapshot
    @contextmanager
    def mutation(self):
        with self.lock: yield
    def require_active_execution(self): assert self.active, 'lease/control lost'
    def append(self, event_type, actor, payload):
        with self.lock:
            assert event_type is EventType.EXECUTION_AUTHORITY_REVALIDATED
            item=ExecutionAuthorityRevalidation.model_validate(payload)
            assert item.prior_snapshot_digest==self.snapshot.snapshot_digest
            if item.effective_snapshot is not None:
                self.snapshot.ensure_not_expanded(item.effective_snapshot); self.snapshot=item.effective_snapshot
            self.events.append(item)


def guard(host=None):
    host=host or Host()
    gate=fresh.FreshERPAuthority(BINDING,REGISTRY,CREDENTIAL,task_id=TASK,client=httpx.Client(transport=httpx.MockTransport(host)))
    snapshot=BoundHostExecutionAuthorityResolver(BINDING).resolve_for_attempt(ExecutionAuthorityResolutionRequest(
        session_id=SID,attempt_number=1,scope=BoundHostExecutionAuthorityResolver(BINDING).scope,validated_at=NOW))
    recorder=Recorder(snapshot)
    event=SessionEvent.create(session_id=SID,sequence=1,event_type=EventType.EXECUTION_AUTHORITY_RESOLVED,
                             actor=EventActor.SYSTEM,payload=snapshot.to_event_payload(),created_at=NOW)
    gate.bind_recorder(lambda:recorder,[event])
    return gate,host,recorder


def refused(call):
    try: call()
    except ExecutionAuthorityResolutionError: pass
    else: raise AssertionError('revoked boundary dispatched')


with patch.dict(os.environ,{'ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES':'erp.example.test'}):
    for mode,reason in [('timeout','probe_timeout'),('malformed','probe_unavailable'),('expand','probe_expiry_invalid'),('drift','host_identity_drift'),('expired','probe_expired')]:
        gate,host,recorder=guard();host.mode=mode
        refused(lambda:gate.check('test'))
        assert recorder.events[-1].reason_code.endswith(reason),recorder.events[-1]
    gate,host,recorder=guard()
    gate.check('first')
    assert host.calls[-1]['toolCallId'] and host.calls[-1]['idempotencyKey']
    assert recorder.events[-1].expires_at<=CONTEXT.expires_at
    # Live cloud lease/JWT + revoked host -> no file, command, MCP, management/client or model dispatch.
    for name in ('files.read','files.list','files.search','files.publish','command.run','mcp.test','skills.read','extensions.list','client.test','erpnext.read'):
        gate,host,recorder=guard();gate.check('first');host.mode='revoke'
        local=NS(execute=Mock(),model_tools=())
        gateway=WorkerToolGateway(local=local,fresh_authority_check=gate.check)
        call=ToolCall(tool_call_id=uuid4(),name=name,arguments={},created_at=NOW)
        result=gateway.execute(call);assert result.status.value=="failed" and result.metadata["execution_state"]=="not_executed"
        local.execute.assert_not_called()
        assert CONTEXT.expires_at>datetime.now(UTC) and recorder.active
        assert str(call.tool_call_id) in recorder.events[-1].reason_code
    gate,host,recorder=guard()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i:gate.check('parallel',str(i)),range(24)))
    assert len(recorder.events)==24 and len(host.calls)==24
    # Selected Bound identity is preserved, including its native renewal method.
    gate,host,recorder=guard()
    resolver,scope,provider=select_attempt_authority(None,None,None,None,SID,binding=BINDING,fresh_checker=gate.probe)
    assert isinstance(resolver,BoundHostExecutionAuthorityResolver) and resolver.fresh_checker==gate.probe
    resolver.resolve_for_attempt(ExecutionAuthorityResolutionRequest(session_id=SID,attempt_number=1,scope=scope,validated_at=NOW))
    host.mode='revoke'
    refused(lambda:resolver.resolve_for_attempt(ExecutionAuthorityResolutionRequest(session_id=SID,attempt_number=1,scope=scope,validated_at=NOW)))
    # Provider internal retry shares its existing request ID; revocation blocks the SECOND HTTP attempt.
    gate,host,recorder=guard(); sent=[]
    def model_request(request):
        sent.append(request);host.mode='revoke'
        return httpx.Response(503,json={'error':{'message':'test retry','type':'server_error'}})
    model=OpenAICompatibleModelGateway(provider_name='openai',base_url='https://model.example.test/v1',api_key='test-only',model_name='test-only',
                                      client=httpx.Client(transport=httpx.MockTransport(model_request)),max_retries=1)
    gate.model(model)
    refused(lambda:model.complete([]));assert len(sent)==1
    assert len(recorder.events)==2
    ids=[x.reason_code.split(':')[2] for x in recorder.events];assert ids[0]==ids[1]
    gate,host,recorder=guard();host.mode='revoke';sent.clear();gate.model(model)
    refused(lambda:model.complete_stream([],on_text_delta=lambda delta:None));assert sent==[]
    # Disabled defaults and startup failure for incomplete/cross-namespace composition.
    with patch.dict(os.environ,{'ZEBRA_ERPNEXT_FRESH_AUTHORITY':'disabled'}): assert not fresh.enabled('erpnext')
    with patch.dict(os.environ,{'ZEBRA_ERPNEXT_FRESH_AUTHORITY':'enabled'}):
        for namespace in ('trench',None):
            try:fresh.enabled(namespace)
            except ValueError:pass
            else:raise AssertionError('namespace accepted')
        try:fresh.validate_wiring('erpnext',None,REGISTRY,NS(host_tool_shared_secret='test-only'))
        except ValueError:pass
        else:raise AssertionError('missing loader accepted')

# Source seams are asserted separately from behavioral contracts; no fabricated E2E claim.
root=Path(__file__).resolve().parents[1]
source=(root/'overrides/apps/worker/src/zebra_agent_worker/execution.py').read_text()
assert source.index('self._erp_workspace_containment.require')<source.index('FreshERPAuthority.for_execution')<source.index('worker_progress = finish_preparation')<source.index('inputs = prepare_execution_inputs')
assert 'fresh_authority=fresh' in source
assert 'local_tool_gateway.fresh_authority_check = fresh.check' in source
assert 'erp_fresh_coverage_not_activated' in source
for name in ('openai_compatible','deepseek_responses'):
    text=(root/f'overrides/packages/agent-integrations/src/agent_integrations/{name}.py').read_text()
    assert text.count('self.authority_check(call_id)')==2
    assert text.count('if self.authority_check is not None:')>=2
assert 'sink = checked_sink' in (root/'overrides/apps/worker/src/zebra_agent_worker/progress_recovery.py').read_text()
assert 'fresh_authority_check("transient_start", call_id)' in (root/'overrides/apps/worker/src/zebra_agent_worker/execution_context.py').read_text()
text=(root/'overrides/apps/worker/src/zebra_agent_worker/cloud_memory_recovery.py').read_text()
assert text.index('getattr(recovery, "fresh_maintenance_blocked"')<text.index('pending_reader =')
print('PASS native Host HMAC, typed fresh denials, all-tool entry refusal, model retry/stream refusal, parallel journal, expiry clamp and source wiring')

# Durable and repair publication both use the same checked sink, before any canonical output.
from agent_core.harness.models import HarnessEventDraft
from zebra_agent_worker import progress_recovery, execution, cloud_memory_recovery
with patch.dict(os.environ,{'ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES':'erp.example.test'}):
    gate,host,recorder=guard();host.mode='revoke';published=[]
    progress=progress_recovery.WorkerProgressRecovery(NS(),NS(state=NS(pending_commentary=None,terminal=False,attempt_number=1)),lambda:None,8,
                                                      fresh_authority_check=gate.check)
    draft=HarnessEventDraft(EventType.PUBLIC_OUTPUT,EventActor.HARNESS,{'output_id':'output-existing','phase':'answer','attempt_number':1})
    with patch.object(progress_recovery,'repair_commentary',lambda *a:None):
        sink=progress.persist_with(published.append);refused(lambda:sink(draft))
    assert not published
    gate,host,recorder=guard();host.mode='revoke';progress.fresh_authority_check=gate.check
    progress.head.state.pending_commentary=object()
    with patch.object(progress_recovery,'repair_commentary',lambda recovery,sink:sink(draft)):
        refused(lambda:progress.persist_with(published.append))
    assert not published
    # Denied early source cannot reach progress/attachment input recovery.
    fake_gate=NS(probe=lambda now:fresh.FreshDecision(fresh.ExecutionAuthorityDecision.DENIED,None,'test_revoked'))
    claimed=NS(lease=NS(session_id=SID),recovery=NS(workspace=NS()))
    service=NS(_erp_fresh_enabled=True,_erp_workspace_containment=NS(require=Mock()))
    with patch.object(execution,'recover_committed_completion',return_value=None), \
         patch.object(fresh.FreshERPAuthority,'for_execution',return_value=fake_gate), \
         patch.object(execution,'recover_execution_progress') as recover:
        refused(lambda:execution.SessionExecutionService._execute_claimed_session_once(service,claimed,started_at=NOW,ownership_check=lambda:None))
        recover.assert_not_called()
    projection=NS(list_memory_recovery_sessions=Mock())
    cloud_memory_recovery.recover_completed_cloud_memory(worker_id='check',batch_size=1,lease_ttl_seconds=10,
        recovery=NS(fresh_maintenance_blocked=True),projection_store=projection)
    projection.list_memory_recovery_sessions.assert_not_called()
print('PASS early no-input boundary, durable/repair publication refusal and maintenance pre-query skip')

# Load the real Host callback + native cloud.owned with a strict Frappe boundary double.
import importlib.util
import sys
from types import ModuleType
from zoneinfo import ZoneInfo

frappe=ModuleType('frappe');utils=ModuleType('frappe.utils');package=ModuleType('zebra_erpnext');package.__path__=[]
frappe.PermissionError=type('PermissionError',(ValueError,),{})
frappe.ValidationError=type('ValidationError',(ValueError,),{})
frappe.session=NS(user='Guest');frappe.flags=NS(zebra_tool_call=False)
local_now=NOW.astimezone(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None)
record=NS(user='qa-user',company='QA Company',conversation='conversation',run_id=RUN,workspace_ref=CONTEXT.workspace_ref,
          expires_at=local_now+timedelta(minutes=5))
conversation=NS(name='conversation',user='qa-user',company='QA Company',task_id=TASK,host_thread='host-thread',
                active_run_id=RUN,workspace_ref=CONTEXT.workspace_ref,status='running')
state={'enabled':1,'company':True,'paused':False}
def throw(message,*args):raise frappe.PermissionError(message)
frappe.throw=throw
frappe.set_user=lambda user:setattr(frappe.session,'user',user)
frappe.whitelist=lambda **kwargs:lambda fn:fn
frappe.as_json=lambda value:json.dumps(value,default=str)
frappe.db=NS(get_value=lambda doctype,*args,**kwargs:record if doctype=='Zebra Grant' else state['enabled'])
def permission(kind):
    assert kind=='read' and frappe.session.user=='qa-user'
    if not state['company']:throw('Company read removed')
frappe.get_doc=lambda doctype,name:conversation if doctype=='Zebra Conversation' else NS(check_permission=permission)
utils.get_datetime=lambda value:datetime.fromisoformat(value) if isinstance(value,str) else value
utils.now_datetime=lambda:local_now
utils.get_system_timezone=lambda:'Asia/Shanghai'
frappe.utils=utils
frappe.conf={'zebra_agent':dict(enabled=True,base_url='https://cloud.test',issuer='https://erp.example.test',origin='https://erp.example.test',
                              signing_key='unused',ca_file='unused',host_secret='test-only-hmac')}
responses=ModuleType('werkzeug.wrappers');responses.Response=object

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module;spec.loader.exec_module(module);return module

with patch.dict(sys.modules,{'frappe':frappe,'frappe.utils':utils,'zebra_erpnext':package,'werkzeug.wrappers':responses,'requests':ModuleType('requests')}):
    cloud=load('zebra_erpnext.cloud',root/'host-baseline/zebra_erpnext/cloud.py');package.cloud=cloud
    authority=load('zebra_erpnext.authority',root/'host-overrides/zebra_erpnext/authority.py')
    gateway=load('zebra_erpnext.gateway',root/'host-overrides/zebra_erpnext/gateway.py');gateway.raw=lambda value:value
    gate,host,recorder=guard()
    # Real native HostToolGateway generated the body/headers; use it unchanged at Frappe's boundary.
    requests=[]
    def capture(request):
        requests.append(request);return host(request)
    gate.client=httpx.Client(transport=httpx.MockTransport(capture))
    with patch.dict(os.environ,{'ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES':'erp.example.test'}):
        gate.probe(NOW).require_allowed()
    native=requests[-1]
    frappe.local=NS(request=NS(method='POST',headers=native.headers,get_json=lambda **kwargs:json.loads(native.content)))
    result=json.loads(gateway.invoke()['output'])
    # Shanghai 8-hour offset: 5-minute local Grant clamps the 10-minute UTC context.
    assert datetime.fromisoformat(result['expires_at'])==NOW+timedelta(minutes=5)
    assert frappe.session.user=='Guest' and not frappe.flags.zebra_tool_call
    for change in ('disabled','company','owner','company_drift','workspace','task','thread','run','deleted','cancelled','paused','naive'):
        before=vars(conversation).copy(); original_record=vars(record).copy(); original_json=frappe.local.request.get_json
        if change=='disabled':state['enabled']=0
        elif change=='company':state['company']=False
        elif change=='owner':conversation.user='someone-else'
        elif change=='company_drift':conversation.company='Different Company'
        elif change=='workspace':conversation.workspace_ref='different'
        elif change=='task':conversation.task_id='different'
        elif change=='thread':conversation.host_thread='different'
        elif change=='run':conversation.active_run_id='different'
        elif change in ('deleted','cancelled'):conversation.status=change
        elif change=='paused':frappe.conf['zebra_agent']['admission_paused']=True
        elif change=='naive':
            args=dict(gate.arguments,expires_at=local_now.isoformat())
            frappe.session.user='qa-user'
            try:authority.check(record,args)
            except frappe.PermissionError:pass
            else:raise AssertionError('naive frozen expiry accepted')
            frappe.session.user='Guest';continue
        try:gateway.invoke()
        except frappe.PermissionError:pass
        else:raise AssertionError('Host accepted '+change)
        assert frappe.session.user=='Guest'
        vars(conversation).update(before);vars(record).update(original_record)
        state.update(enabled=1,company=True);frappe.conf['zebra_agent'].pop('admission_paused',None)
        frappe.local.request.get_json=original_json
    # Bad signature must fail before user delegation.
    frappe.local.request.headers=dict(native.headers)|{'X-Zebra-Host-Auth':'bad'}
    try:gateway.invoke()
    except frappe.PermissionError:pass
    else:raise AssertionError('invalid signature accepted')
    assert frappe.session.user=='Guest'
print('PASS real Host HMAC/delegated/owned callback with disabled-user, Company removal, owner/task/thread/run drift, pause/cancel and Asia/Shanghai clamp mocks')

# The native outer fence checks before scheduling/payloads; actual dispatch retains uncertainty semantics.
from agent_tools.effect_guard import FencedEffectToolGateway
from agent_tools.effect_guard_support import effect_identity
with patch.dict(os.environ,{'ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES':'erp.example.test'}):
    gate,host,recorder=guard();host.mode='revoke'
    effect=FencedEffectToolGateway.__new__(FencedEffectToolGateway)
    effect._ownership_check=lambda:None;effect._fresh_authority_check=gate.check
    effect._gateway=NS(execute=Mock());effect._schedule=Mock()
    call=ToolCall(tool_call_id=uuid4(),name='command.run',arguments={'command':'unused'},created_at=NOW)
    identity=effect_identity(call,'unchanged-authority')
    refused(lambda:effect.execute(call));effect._schedule.assert_not_called();effect._gateway.execute.assert_not_called()
    assert effect_identity(call,'unchanged-authority')==identity
    gate,host,recorder=guard();host.mode='revoke';effect._fresh_authority_check=gate.check
    effect._mutation_guard=recorder.mutation;effect._execution_started=Mock()
    effect._dispatch=NS(fail_no_effect=Mock(return_value='terminal'),mark_uncertain=Mock(return_value='uncertain'))
    effect._terminal_event=Mock(return_value='event');effect._accept_event=Mock()
    claim=NS(dispatch=NS(dispatch_id=uuid4()))
    refused(lambda:effect._execute_claim(claim,call))
    effect._dispatch.fail_no_effect.assert_called_once();effect._dispatch.mark_uncertain.assert_not_called()
    effect._gateway.execute.assert_not_called();effect._execution_started.assert_not_called()
    # After dispatch starts the unchanged native catch keeps uncertainty; it never retries business work.
    effect._fresh_authority_check=None;effect._gateway.execute=Mock(side_effect=RuntimeError('uncertain test'))
    try:effect._execute_claim(claim,call)
    except RuntimeError:pass
    else:raise AssertionError('uncertain effect swallowed')
    effect._dispatch.mark_uncertain.assert_called_once();effect._gateway.execute.assert_called_once_with(call)
print('PASS native fenced outer admission, failed-no-effect before dispatch and unchanged uncertain-effect handling')

# SPEC regression 1: actual shared execution entry blocks completion payloads in READY/RUNNING.
from zebra_agent_worker import completion_recovery, context_materialization
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.execution_authority import ExecutionAuthoritySnapshot
for status in (SessionStatus.READY,SessionStatus.RUNNING):
    for committed in (False,True):
        payloads=([NS(event_type=EventType.ANSWER_COMMITTED,payload={'assistant_message':'private'})] if committed else [])
        completion_reader=Mock(return_value=payloads)
        factory=NS(completion_reader=completion_reader,build=Mock(return_value=NS(worker_mutation_authority='lease-valid')))
        service=NS(_erp_fresh_enabled=True,_erp_workspace_containment=None,_projection_recorder_factory=factory)
        claimed=NS(lease=NS(session_id=SID),recovery=NS(session=NS(status=status),workspace=NS()))
        fake_gate=NS(probe=lambda now:fresh.FreshDecision(fresh.ExecutionAuthorityDecision.REVOKED,None,'test_revoked'))
        with patch.object(fresh.FreshERPAuthority,'for_execution',return_value=fake_gate), \
             patch.object(execution,'recover_execution_progress') as progress:
            refused(lambda:execution.SessionExecutionService._execute_claimed_session_once(service,claimed,started_at=NOW,ownership_check=lambda:None))
        completion_reader.assert_not_called();factory.build.assert_not_called();progress.assert_not_called()
# Disabled mode preserves native completion first, without loading fresh Task bindings.
with patch.object(execution,'recover_committed_completion',return_value='already-committed') as recover, \
     patch.object(fresh.FreshERPAuthority,'for_execution') as create:
    service=NS(_erp_fresh_enabled=False)
    assert execution.SessionExecutionService._execute_claimed_session_once(service,claimed,started_at=NOW,ownership_check=lambda:None)=='already-committed'
    create.assert_not_called();recover.assert_called_once()

# SPEC regression 2: outer fresh succeeds, inner fresh rejects; native result is exactly failed_no_effect.
with patch.dict(os.environ,{'ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES':'erp.example.test'}):
    gate,host,recorder=guard()
    local=NS(execute=Mock())
    def check_boundary(boundary,identity):
        if boundary.startswith('tool:'):host.mode='revoke'
        gate.check(boundary,identity)
    inner=WorkerToolGateway(local=local,fresh_authority_check=check_boundary)
    effect=FencedEffectToolGateway.__new__(FencedEffectToolGateway)
    effect._ownership_check=lambda:None;effect._fresh_authority_check=check_boundary
    effect._gateway=inner;effect._mutation_guard=recorder.mutation;effect._execution_started=Mock()
    effect._effect_payloads=None
    effect._dispatch=NS(fail_no_effect=Mock(return_value='no-effect'),mark_uncertain=Mock(),complete=Mock())
    effect._terminal_event=Mock(return_value='terminal');effect._accept_event=Mock()
    call=ToolCall(tool_call_id=uuid4(),name='command.run',arguments={'command':'never-run'},created_at=NOW)
    identity=effect_identity(call,'same-authority');claim=NS(dispatch=NS(dispatch_id=uuid4()))
    result=effect._execute_claim(claim,call)
    assert result.tool_call_id==call.tool_call_id and result.metadata['execution_state']=='not_executed'
    assert effect_identity(call,'same-authority')==identity
    effect._dispatch.fail_no_effect.assert_called_once();effect._dispatch.mark_uncertain.assert_not_called()
    effect._dispatch.complete.assert_not_called();local.execute.assert_not_called()
    assert [x.reason_code.split(':')[1] for x in recorder.events]==['effect_dispatch','tool']
    assert gate._denied
    refused(lambda:gate.check('model','unchanged-provider-id'))
    local.execute.assert_not_called()

# SPEC regression 3: real prepare_worker_context + AttemptAuthorityEvidence.persist + Bound resolver.
class ContextRecorder(Recorder):
    def __init__(self):
        super().__init__(None);self.canonical=[];self.session=NS(session_id=SID,current_sequence=0)
        self._ownership_check=lambda:None;self.worker_mutation_authority=None
    def append(self,kind,actor,payload,**kwargs):
        with self.lock:
            if kind is EventType.EXECUTION_AUTHORITY_RESOLVED:
                assert self.snapshot is None
                self.snapshot=ExecutionAuthoritySnapshot.model_validate(payload)
            else:super().append(kind,actor,payload)
            self.session.current_sequence+=1
            self.canonical.append(SessionEvent.create(session_id=SID,sequence=self.session.current_sequence,
                event_type=kind,actor=actor,payload=payload,created_at=datetime.now(UTC)))

with patch.dict(os.environ,{'ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES':'erp.example.test'}):
    for revoked in (True,False):
        gate,host,_=guard();journal=ContextRecorder();seen=[]
        def callback(request):
            result=host(request)
            if revoked and len(host.calls)==2:host.mode='revoke'  # after selected resolver's initial allow
            return result
        gate.client=httpx.Client(transport=httpx.MockTransport(callback))
        claimed=NS(lease=NS(session_id=SID),recovery=NS(session=journal.session,workspace=NS(workspace_root=Path('/unused'))))
        def recover_session(*args,**kwargs):
            seen.append(journal.session.current_sequence)
            return NS(session=NS(session_id=SID,current_sequence=journal.session.current_sequence),
                      workspace=claimed.recovery.workspace)
        def read_inputs(*args):return list(journal.canonical)
        materialize=Mock(return_value=None)
        with patch.object(context_materialization,'recover_turn_extension',return_value=None), \
             patch.object(context_materialization,'materialize_worker_context',materialize):
            def prepare():
                return context_materialization.prepare_worker_context(store=NS(),task_binding_loader=lambda sid:BINDING,
                    resolver=None,static_scope=None,scope_provider=None,recovery_service=NS(recover_session=recover_session),event_store=NS(),recorder=journal,
                    claimed=claimed,events=[],task=NS(),active_capsule_id=None,as_of=NOW,ownership_check=lambda:None,fresh_authority=gate,
                    execution_input_reader=read_inputs)
            if revoked:refused(prepare)
            else:prepared=prepare()
        assert len(journal.canonical)==2
        initial=ExecutionAuthoritySnapshot.model_validate(journal.canonical[0].payload)
        checked=ExecutionAuthorityRevalidation.model_validate(journal.canonical[1].payload)
        assert checked.prior_snapshot_digest==initial.snapshot_digest
        assert checked.reason_code.startswith('erp_fresh:context_materialization:')
        if revoked:
            materialize.assert_not_called();assert checked.decision.value=='denied';assert seen==[1]
        else:
            materialize.assert_called_once();assert checked.decision.value=='narrowed';assert seen==[1,2]
            assert materialize.call_args.kwargs['session'].current_sequence==2
            assert materialize.call_args.kwargs['events']==journal.canonical
            assert prepared.claimed.recovery.session.current_sequence==2 and prepared.events==journal.canonical
print('PASS SPEC regressions: completion-before-payload guard, inner rejection/no-effect, post-persist context journal and refreshed revisions')

# Only the entry fresh check is converted; authority errors from an already-started handler stay uncertain.
local=NS(execute=Mock(side_effect=ExecutionAuthorityResolutionError('started handler failure')))
inner=WorkerToolGateway(local=local,fresh_authority_check=lambda *args:None)
effect._gateway=inner;effect._fresh_authority_check=None
effect._dispatch.mark_uncertain.reset_mock();effect._dispatch.fail_no_effect.reset_mock()
refused(lambda:effect._execute_claim(claim,call))
local.execute.assert_called_once_with(call)
effect._dispatch.mark_uncertain.assert_called_once();effect._dispatch.fail_no_effect.assert_not_called()
print('PASS started-handler authority exception preserves native uncertain result')

# Shared stored-binding validation: both native readers compare the same latest row's persisted digest.
import ast
from agent_core.domain.identifiers import SessionId, TaskId
from agent_storage.postgres import task_admission
from psycopg import IsolationLevel
from uuid import UUID

class BindingConnection:
    def __init__(self,row):self.row=row;self.queries=[];self.isolation=None;self.readonly=None
    def execute(self,sql,params=None):
        self.queries.append((sql,params))
        if 'task_binding_snapshots' in sql:
            assert 'SELECT binding_digest, snapshot_json FROM task_binding_snapshots' in sql
            assert 'ORDER BY binding_revision DESC LIMIT 1' in sql
            assert 'deployment_namespace=' in sql
            assert params is not None and 'erpnext' in params
        return self
    def fetchone(self):return self.row
    def fetchall(self):return [self.row]
    def set_isolation_level(self,value):self.isolation=value
    def set_read_only(self,value):self.readonly=value
    def __enter__(self):return self
    def __exit__(self,*args):pass

root=SessionId(UUID(TASK))
def binding_row(digest=BINDING.binding_digest):
    return dict(root_session_id=TASK,snapshot_json=BINDING.model_dump(mode='json'),binding_digest=digest)

def bad_binding(call):
    try:call()
    except ValueError as error:assert 'stored task binding digest' in str(error)
    else:raise AssertionError('invalid persisted binding digest accepted')

for direct in (True,False):
    for digest in (BINDING.binding_digest,'0'*64,None,42,b'a'*64,'A'*64,'g'*64,'a'*63,'a'*65,'a'*64+'\n'):
        row=binding_row(digest)
        if digest is None:row.pop('binding_digest')
        connection=BindingConnection(row)
        database=NS(connect=lambda:connection,connect_task_io=lambda:connection)
        with patch.object(task_admission,'PostgresDatabase',return_value=database), \
             patch.object(task_admission,'root_for_session',return_value=root), \
             patch.object(task_admission,'derive_lineage',return_value=[{'session_id':SID}]):
            def load():
                if direct:return task_admission.load_task_binding('unused',deployment_namespace='erpnext',task_id=TaskId(root))
                return task_admission.load_session_task_binding('unused',deployment_namespace='erpnext',session_id=SID)
            if digest==BINDING.binding_digest:assert load()==BINDING
            else:bad_binding(load)
        if direct:assert connection.queries[0][0]=='SET TRANSACTION READ ONLY'
        else:assert connection.isolation==IsolationLevel.REPEATABLE_READ and connection.readonly is True
# Absence remains optional; existing lineage checks still fail closed.
assert task_admission._read_task_binding(BindingConnection(None),'erpnext',TaskId(root)) is None
with patch.object(task_admission,'derive_lineage',return_value=[]):
    try:task_admission.read_session_task_binding(BindingConnection(binding_row()),'erpnext',root)
    except ValueError as error:assert 'native Task lineage' in str(error)
    else:raise AssertionError('missing lineage accepted')

# Execute the actual composition closure, then the real fresh execution entry and shared loader chain.
loop_source=Path(__file__).resolve().parents[1]/'overrides/apps/worker/src/zebra_agent_worker/loop.py'
loader_node=next(node for node in ast.walk(ast.parse(loop_source.read_text()))
                 if isinstance(node,ast.FunctionDef) and node.name=='task_binding_loader')
loader_scope=dict(SessionId=SessionId,active_namespace='erpnext',binding_dsn='unused',
                  _load_binding=task_admission.load_session_task_binding)
exec(compile(ast.Module(body=[loader_node],type_ignores=[]),str(loop_source),'exec'),loader_scope)
connection=BindingConnection(binding_row('0'*64))
completion_reader=Mock(side_effect=AssertionError('private completion payload read'))
factory=NS(completion_reader=completion_reader,build=Mock(side_effect=AssertionError('private recorder constructed')))
service=NS(_erp_fresh_enabled=True,_erp_workspace_containment=None,_projection_recorder_factory=factory,
    _task_index_store=NS(task_id_for_session=lambda sid:TaskId(root)),_task_binding_loader=loader_scope['task_binding_loader'],
    _egress_registry=REGISTRY,_settings=NS(host_tool_shared_secret='test-only-hmac'))
claimed=NS(lease=NS(session_id=SID),recovery=NS(session=NS(status=SessionStatus.RUNNING),workspace=NS()))
with patch.object(task_admission,'PostgresDatabase',return_value=NS(connect=lambda:connection)), \
     patch.object(fresh.FreshERPAuthority,'probe') as probe, \
     patch.object(execution,'recover_execution_progress') as progress:
    bad_binding(lambda:execution.SessionExecutionService._execute_claimed_session_once(
        service,claimed,started_at=NOW,ownership_check=lambda:None))
probe.assert_not_called();completion_reader.assert_not_called();factory.build.assert_not_called();progress.assert_not_called()
print('PASS shared stored digest: both native readers, valid/mismatch/missing/malformed, readonly/lineage, composed fresh loader 0 probe/private recovery')

# QUALITY: execute the shared startup block and all native direct-event constructors.
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.domain.leases import LeaseFence
from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.recovery import RecoveredSession
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker import execution_continuations

startup_node=next(node for node in ast.walk(ast.parse(inspect.getsource(execution)))
    if isinstance(node,ast.With) and any(isinstance(item.context_expr,ast.Call)
    and item.context_expr.args and isinstance(item.context_expr.args[0],ast.Constant)
    and item.context_expr.args[0].value=='continuation start lost a sequence race' for item in node.items))
startup_code=compile(ast.Module(body=[startup_node],type_ignores=[]),'<shared-continuation-start>','exec')
for kind in ('approved','completed','clarification','child_wakeup','client_effect'):
    for concurrent in (False,True):
        gate,host,prior=guard()
        primary=NS(session=Session(session_id=SID,title='test',status=SessionStatus.READY,
            created_at=NOW,updated_at=NOW,current_sequence=1),
            workspace=WorkspaceProjection(session_id=SID,workspace_root='/unused',prepared_at=NOW,
                updated_at=NOW,current_sequence=1,status=WorkspaceStatus.PREPARED))
        accepted=[];cas_rejections=[]
        fence=LeaseFence(control_plane_epoch=uuid4(),fencing_token=1,owner_instance_id="test-worker")
        def commit(event,session,workspace,*,authority):
            if authority.expected_stream_revision!=primary.session.current_sequence:
                cas_rejections.append(event)
                raise ValueError('test independent primary CAS conflict')
            assert event.sequence==primary.session.current_sequence+1
            primary.session,primary.workspace=session,workspace;accepted.append(event)
            return NS(event=event,session=session,workspace=workspace)
        recorder=DurableHarnessEventRecorder(session=primary.session,workspace=primary.workspace,
            event_store=NS(read_since=lambda *args:[]),projection_store=NS(get_session=lambda sid:primary.session),
            workspace_store=NS(),model_call_indexer=Mock(),tool_run_indexer=Mock(),
            worker_projection_transaction=NS(commit_worker_event=commit),
            worker_mutation_authority=WorkerMutationAuthority(deployment_namespace='erpnext',session_id=SID,
                expected_stream_revision=1,lease_fence=fence))
        def recover(*args,**kwargs):
            return RecoveredSession(primary.session,primary.workspace,primary.session.current_sequence+1,
                                    primary.session.current_sequence,False)
        recovery=NS(recover_session=Mock(side_effect=recover))
        claimed=ClaimedSession(recover(),NS(session_id=SID,fence=fence))
        initial=SessionEvent.create(session_id=SID,sequence=1,event_type=EventType.EXECUTION_AUTHORITY_RESOLVED,
                                   actor=EventActor.SYSTEM,payload=prior.snapshot.to_event_payload(),created_at=NOW)
        gate.bind_recorder(lambda:recorder,[initial])
        with patch.dict(os.environ,{'ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES':'erp.example.test'}):
            gate.check('extension_materialization');gate.check('context_injection')
        assert recorder.session.current_sequence==3 and claimed.recovery.session.current_sequence==1
        call=ToolCall(tool_call_id=uuid4(),name='command.run',arguments={},created_at=NOW)
        continuation=NS(tool_call=call,completed_output='done' if kind=='completed' else None,
                        metadata={},effect_id=str(uuid4()))
        selected=execution_continuations.ActiveContinuations(
            approved=continuation if kind in ('approved','completed') else None,
            clarification=continuation if kind=='clarification' else None,
            child_wakeup=continuation if kind=='child_wakeup' else None,
            client_effect=continuation if kind=='client_effect' else None)
        def select(*args,**kwargs):
            if concurrent:  # independent writer wins after refresh, before first direct append
                primary.session=primary.session.model_copy(update={'current_sequence':4})
                primary.workspace=primary.workspace.model_copy(update={'current_sequence':4})
            return selected
        scope=dict(execution.__dict__,fresh=gate,authority_recorder=recorder,claimed=claimed,
            self=NS(_recovery_service=recovery,_delegation_store=None,_projection_store=None),
            ownership_check=lambda:None,session_events=[initial],execution_events=NS(),started_at=NOW,
            release_gateway=lambda:None,attempt_number=2)
        with patch.object(execution_continuations,'recover_active_continuations',side_effect=select):
            if concurrent:
                try:exec(startup_code,scope)
                except ValueError as error:assert 'CAS conflict' in str(error)
                else:raise AssertionError('concurrent primary advance ignored')
                assert len(cas_rejections)==1 and len(accepted)==2
                assert recorder.session.current_sequence==3
            else:
                exec(startup_code,scope)
                assert scope['continuations'] is selected
                starts=accepted[2:]
                assert [event.sequence for event in starts]==([4,5] if kind=='approved' else [4])
                identity=starts[-1].payload.get('tool_call_id',starts[-1].payload.get('clarification_id'))
                assert identity==str(call.tool_call_id)
                if kind=='client_effect':assert starts[0].payload['client_effect_id']==continuation.effect_id
                assert scope['claimed'].lease is claimed.lease
                assert scope['claimed'].recovery.session.current_sequence==starts[-1].sequence
                assert scope['claimed'].recovery.workspace.current_sequence==starts[-1].sequence
                # Refresh reused the recorder's committed Cloud projection; recovery is only the native post-start read.
                recovery.recover_session.assert_called_once()
print('PASS shared continuation startup: fresh journal -> native refresh -> all five native start branches; stable IDs and independent CAS conflict refusal')
