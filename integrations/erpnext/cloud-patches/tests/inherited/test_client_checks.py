"""Run: python3 tests/test_client_checks.py; credential admission and wire recovery."""
import importlib.util
import json
from pathlib import Path
import sys
import types
from uuid import uuid4
class Rejected(Exception): pass
f=types.ModuleType('frappe');f.throw=lambda message,*args:(_ for _ in ()).throw(Rejected(message))
f.PermissionError=Rejected;f.parse_json=json.loads
f.db=types.SimpleNamespace(commit=lambda:None)
f.local=types.SimpleNamespace(request=types.SimpleNamespace(headers={'Origin':'https://erp.test'}))
f.conf={}
c=types.ModuleType('zebra_erpnext.cloud')
profile={'actions':[{'name':'erpnext.ui.document.open'}], 'revision':1,'digest':'digest','action_digests':{}}
c.config=lambda:{'frontend_profile':profile,'origin':'https://erp.test'}
c.require_admission_open=lambda *args:None
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.modules.update({'frappe':f,'zebra_erpnext.cloud':c})
from zebra_erpnext import client
class Doc:
    name='test';user='user';task_id='task';active_run_id='run';client_surface_json=None
    def db_update(self): pass
doc=Doc();c.owned=lambda _,**kw:doc;calls=[]
opened={'client_session_id':str(uuid4()),'session_credential':'credential','controller_fence_token':'fence','binding_id':'binding','binding_digest':'digest'}
def request(doc,method,path,**kw):
    calls.append((method,path,kw))
    return opened
c.request=request
first=client.open_surface(doc,'run',{},types.SimpleNamespace(owned=lambda:True))
assert client.open_surface(doc,'run',{},types.SimpleNamespace(owned=lambda:True))==first and len(calls)==1
# A saved admission marker survives loss of a credential-bearing response.
doc.client_surface_json=None
c.request=lambda *args,**kwargs:(_ for _ in ()).throw(Rejected('ack lost'))
try:client.open_surface(doc,'run',{},types.SimpleNamespace(owned=lambda:True))
except Rejected:pass
else:raise AssertionError('Missing lost-ack simulation')
assert json.loads(doc.client_surface_json)['opening_run']=='run'
c.request=lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError('blind credential reopen'))
try:client.open_surface(doc,'run',{},types.SimpleNamespace(owned=lambda:True))
except Rejected:pass
else:raise AssertionError('Unknown surface was blindly reopened')
# New run cleans up an expired session, accepting only the declared problem.
doc.client_surface_json=json.dumps(first);doc.active_run_id='next';calls=[];c.request=request
client.open_surface(doc,'next',{},types.SimpleNamespace(owned=lambda:True))
assert calls[0][1].endswith('/release')
assert (401,'client_session_authorization_required') in calls[0][2]['accepted_problems']
# The SDK's receipt idempotency key must survive the same-origin RPC bridge.
class Response:
    status_code=400
    def json(self):return {'status':'invalid'}
    def close(self):pass
calls=[]
states=iter(['running','waiting_client_effect'])
def receipt_request(*args, **kwargs):
    calls.append((args, kwargs))
    if args[1]=='GET' and args[2].endswith('/header'):return {'status':next(states)}
    if args[1]=='GET' and '/client-effects/' in args[2]:return {'status':'pending'}
    return Response()
c.request=receipt_request
surface=json.loads(doc.client_surface_json)
effect=str(uuid4())
r=client.proxy('conversation',f'/v1/client-effects/{effect}/receipts','POST','{}',surface['sessionCredential'],surface['controllerFenceToken'])
assert r['status']==400 and calls[-1][1]['key']=='sdk-receipt:'+effect
assert any(args[2].endswith('/header') for args,_ in calls if isinstance(args, tuple))
r=client.proxy('conversation',f"/v1/client-sessions/{surface['clientSessionId']}/effects",'GET','',surface['sessionCredential'],surface['controllerFenceToken'])
assert calls[-1][1]['body'] is None and r['status']==400
print('PASS surface reuse, lost credential ACK, expired cleanup and receipt/GET proxy semantics')

c.require_admission_open=lambda *args:(_ for _ in ()).throw(Rejected("maintenance"))
before=(len(calls),doc.client_surface_json)
try:client.open_surface(doc,"paused",{},types.SimpleNamespace(owned=lambda:True))
except Rejected as e:assert str(e)=="maintenance"
else:raise AssertionError("Paused surface mutated admission")
assert (len(calls),doc.client_surface_json)==before
print("PASS maintenance pauses surface creation before its admission marker")
