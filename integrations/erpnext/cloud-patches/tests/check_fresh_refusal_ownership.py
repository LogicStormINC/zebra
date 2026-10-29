"""Actual BFF/Cloud ownership functions with expiring-token/row-lock IO doubles.

Distinct loaded Documents deliberately retain stale values. Network doubles run
successor requests while an earlier sender is suspended; no real Cloud IO occurs.
Native Redis/MariaDB primitives require Root's separate Frappe QA acceptance.
"""
from copy import deepcopy
from datetime import datetime,UTC
import json
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace as Simple
from uuid import uuid4

class Rejected(Exception):pass
class LockError(Exception):pass
class Admission:
    def __init__(self,*a,**kw):self.token=str(uuid4())
    def __enter__(self):
        global token
        if token is not None:raise LockError('busy')
        token=self.token
        return self
    def owned(self):return token==self.token
    def __exit__(self,*a):
        global token
        if not self.owned():raise LockError('expired')
        token=None
class Doc:
    def __init__(self,values):self.__dict__.update(deepcopy(values))
    def db_update(self):
        global stored
        assert row_locked,'whole Document update without fresh row lock'
        stored=deepcopy(self.__dict__)
    def update(self,values):self.__dict__.update(values)
    def get(self,key):return getattr(self,key,None)

def commit():
    global row_locked
    row_locked=False

def get_doc(doctype,name=None,**kw):
    global row_locked,row_wait,grant_inserts
    if isinstance(doctype,dict):
        assert doctype['doctype']=='Zebra Grant'
        def insert():
            global grant_inserts
            grant_inserts+=1
        return Simple(db_insert=insert)
    if doctype=='Company':return Simple(check_permission=lambda *a:None)
    assert doctype=='Zebra Conversation' and name==stored['name']
    if kw.get('for_update'):
        if row_wait:
            callback,row_wait=row_wait,None;callback()
        row_locked=True
    return Doc(stored)

def set_value(doctype,name,field,value=None,**kw):
    assert row_locked
    if doctype=='Zebra Conversation':stored.update(field if isinstance(field,dict) else {field:value})

def throw(message,error=None):
    if isinstance(error,Exception):raise error
    raise Rejected(message)

frappe=ModuleType('frappe');frappe.ValidationError=Rejected;frappe.PermissionError=Rejected
frappe.throw=throw;frappe.get_doc=get_doc;frappe.parse_json=json.loads
frappe.session=Simple(user='owner');frappe.cache=Simple(lock=Admission)
frappe.local=Simple(site='qa',request=Simple(headers={'Origin':'https://erp.test'}))
frappe.db=Simple(commit=commit,get_value=lambda *a,**kw:True,set_value=set_value,delete=lambda *a:None)
frappe.conf={'zebra_agent':dict(enabled=True,base_url='https://cloud.test',issuer='https://erp.test',origin='https://erp.test',
    signing_key='not-used',ca_file='not-used',host_secret='not-used',frontend_profile={'actions':[], 'revision':1,'digest':'a'*64,'action_digests':{}})}
utils=ModuleType('frappe.utils');utils.now_datetime=lambda:datetime.now(UTC)
redis=ModuleType('redis');exceptions=ModuleType('redis.exceptions');exceptions.LockError=LockError
sys.modules.update({'frappe':frappe,'frappe.utils':utils,'redis':redis,'redis.exceptions':exceptions})
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'host-overrides'))
from zebra_erpnext import cloud,chat,client,presentation
cloud.subprocess.run=lambda *a,**kw:Simple(stdout=b'test-signature')
class Response:
    def __init__(self,status=200,body=None):self.status_code=status;self.ok=status<400;self.body=body or {}
    def json(self):return self.body
    def close(self):pass

def reset(mode='allow'):
    global stored,token,row_locked,row_wait,operation,predecessor,eid,accepted,posts,behavior,fired,grant_inserts
    token=None;row_locked=False;row_wait=None;accepted={};posts=[];behavior=mode;fired=False;grant_inserts=0
    predecessor=str(uuid4());eid=str(uuid4());operation=str(uuid4())
    stored=dict(name='owned',user='owner',company='QA',title='Title',task_id=str(uuid4()),active_run_id=predecessor,
        status='running',request_id=str(uuid4()),pending_message='original',pending_command=None,stop_command=None,
        prepared_request=None,prepared_revision=0,client_surface_json=None,preferences_json=None,
        host_thread=str(uuid4()),workspace_ref='private',presentation_json=None,
        request_options=json.dumps({'model_profile':chat.MODEL_OPTIONS[0]['value'],'reasoning_effort':'high','context':{}}))

def retry():return chat.retry_fresh('owned',predecessor,eid,operation)
def refuses(call):
    try:call()
    except (Rejected,LockError):return
    raise AssertionError('expired admission was allowed')

def successor(mode='lost_ack'):
    global token,behavior
    token=None;behavior=mode
    refuses(retry) if mode=='lost_ack' else retry()


def wire(method,url,**kw):
    global fired,behavior,token
    path=url.removeprefix('https://cloud.test')
    # Real grant() committed before reaching this network boundary.
    assert not row_locked
    if method=='GET':
        if behavior in {'submit_overlap','cancel_overlap','manage_overlap'} and not fired:
            fired=True;replace_by_successor()
        return Response(body={'status':'completed','active_segment_sequence':3,'command_outcome':{
            'code':'erp_fresh_authority_refused','run_id':predecessor,'accepted_event_id':eid,'retry_eligible':True}})
    if path.endswith('/release'):
        if behavior=='late_release' and not fired:
            fired=True;successor()
        return Response()
    if path.endswith('/client-surface'):
        credentials='later' if fired else 'earlier'
        if behavior=='late_open' and not fired:
            fired=True
            # Native unknown-open wait is respected; expire only this test's
            # clock marker before the explicit successor retry.
            opening=json.loads(stored['client_surface_json']);opening['opening_at']-=421
            stored['client_surface_json']=json.dumps(opening)
            successor()
        return Response(body={'client_session_id':credentials,'session_credential':credentials,
            'controller_fence_token':credentials,'binding_id':credentials,'binding_digest':'b'*64})
    if path=='/tasks':return Response(201,{'task_id':str(uuid4()),'active_segment_sequence':3})
    if path.endswith('/messages'):return Response(202,{'active_segment_sequence':3})
    assert path=='/agui/commands'
    posts.append(deepcopy(kw))
    if behavior=='overlap_403' and not fired:
        fired=True;successor()
        return Response(403,{'reason':'host_binding_renewal_rejected'})
    key=kw['headers']['Idempotency-Key']
    if key in accepted:assert accepted[key]==kw['json']
    accepted.setdefault(key,deepcopy(kw['json']))
    if behavior=='lost_ack':raise cloud.requests.RequestException('unknown ACK')
    return Response(202,{'status':'accepted'})
cloud.requests.request=wire

reset('overlap_403');refuses(retry)
pin=stored['pending_command'];run=stored['active_run_id']
assert pin and run!=predecessor and len(accepted)==1
assert json.loads(stored['request_options'])['fresh_retry']['phase']=='dispatching'
behavior='allow';assert retry()['run_id']==run and len(accepted)==1
assert all(p['json']==json.loads(pin) for p in posts)
print('PASS full BFF A first send expired; B accepted+lostACK; A403 cannot clear B pin/Run; exact retry remains one command')

for mode in ['late_open','late_release']:
    reset(mode)
    if mode=='late_release':stored['client_surface_json']=json.dumps(dict(runId=predecessor,taskId=stored['task_id'],clientSessionId='old',runBindingId='old',sessionCredential='old',controllerFenceToken='old'))
    refuses(retry)
    surface=json.loads(stored['client_surface_json']);pin=stored['pending_command']
    assert surface['sessionCredential']=='later' and pin and len(accepted)==1
    assert surface['runId']==stored['active_run_id']!=predecessor
    behavior='allow';assert retry()['run_id']==surface['runId'] and len(accepted)==1
print('PASS full client helper delayed open/release cannot overwrite successor credentials or dispatch pin')

def replace_by_successor():
    global token
    token=None
    with Admission() as newer:
        doc=cloud.owned('owned',for_update=True,admission_lock=newer)
        doc.title='successor-title';doc.pending_command='successor-pin';doc.active_run_id='successor-run'
        doc.db_update();commit()

for name,call in [('submit',lambda:chat.submit('owned','new message',str(uuid4()))),
                  ('cancel',lambda:chat.cancel('owned')),('manage',lambda:chat.manage('owned',delete=True))]:
    reset(name+'_overlap');refuses(call)
    assert stored['title']=='successor-title' and stored['pending_command']=='successor-pin' and stored['active_run_id']=='successor-run'
print('PASS normal submit/cancel/manage postnetwork writes reject expired ownership and preserve successor coordinates')

reset()
# Simulate waiting on FOR UPDATE: successor wins while caller is waiting. The
# token check must occur after this hook/current-row load, not before the wait.
row_wait=replace_by_successor
refuses(lambda:chat.save_settings('owned',chat.MODEL_OPTIONS[0]['value'],'low'))
assert stored['preferences_json'] is None and stored['title']=='successor-title'
print('PASS token lost while acquiring row lock fails after acquisition; settings cannot overwrite successor')

reset()
def message_then_expire(*args):
    commit();replace_by_successor()
    return {'id':'answer','content':'public'}
presentation._message=message_then_expire
refuses(lambda:presentation.save('owned','answer','d'*64,'helpful'))
assert stored['presentation_json'] is None and stored['title']=='successor-title'
print('PASS shared presentation save postread mutation uses the same current-row/token guard')

reset();stored['task_id']=None;stored['workspace_ref']=None
stale=Doc(stored);stored['title']='newer-title'
cloud.grant(stale)
assert stored['title']=='newer-title' and stored['workspace_ref']
reset();stale=Doc(stored)
with Admission() as expired:
    token=None
    before=deepcopy(stored)
    refuses(lambda:cloud.grant(stale,admission_lock=expired))
    assert stored==before and grant_inserts==0
    token=expired.token  # only allow this synthetic context to close
print('PASS actual grant initialization reloads current row; expired admission cannot create a grant or overwrite Document')

for initial in [False,True]:
    reset()
    if initial:stored['task_id']=None;stored['status']='idle'
    request_id=str(uuid4())
    result=chat.submit('owned','new message',request_id)
    assert result['task_id']==stored['task_id'] and stored['status']=='running'
    assert stored['pending_command'] is None and len(accepted)==1
    assert json.loads(stored['client_surface_json'])['runId']==stored['active_run_id']
    chat.cancel('owned');assert stored['status']=='cancelled'
    chat.save_settings('owned',chat.MODEL_OPTIONS[0]['value'],'low')
    assert json.loads(stored['preferences_json'])['reasoning_effort']=='low'
    chat.manage('owned',title='renamed');assert stored['title']=='renamed'
print('PASS first/followup normal submit, client surface, Stop, settings and rename retain successful shared flow')
