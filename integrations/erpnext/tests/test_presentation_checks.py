"""Run: python3 tests/test_presentation_checks.py. No Frappe/Cloud/model writes."""
import json
from pathlib import Path
import sys
import threading
import types
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
class Rejected(Exception): pass
class LockError(Exception): pass
locks={}
class Lock:
    def __init__(self,name,**kwargs):self.lock=locks.setdefault(name,threading.Lock())
    def __enter__(self):
        if not self.lock.acquire(False):raise LockError()
        return self
    def owned(self):return self.lock.locked()
    def __exit__(self,*args):self.lock.release()
class Doc(dict):
    def __getattr__(self,key):return self.get(key)
    def __setattr__(self,key,value):self[key]=value
    def get_content(self):return self.content
    def insert(self,**kwargs):
        self.owner=frappe.session.user  # native set_user_and_timestamp overrides input owner
        self.name='file-'+str(len(files));files[self.name]=self;return self
    def db_set(self,field,value,*,update_modified,commit):
        assert field=='owner' and value=='Administrator' and not update_modified and not commit
        self[field]=value;owner_updates.append(self.name)
frappe=types.ModuleType('frappe');frappe.throw=lambda message,*args:(_ for _ in ()).throw(Rejected(message))
frappe.PermissionError=Rejected;frappe.cache=types.SimpleNamespace(lock=Lock);frappe.session=types.SimpleNamespace(user='user')
files={};owner_updates=[];doc=Doc(name='own',user='user',company='Company',presentation_json=None,task_id='task',active_run_id='run')
frappe.get_doc=lambda kind,name=None:Doc(kind) if isinstance(kind,dict) else files[name]
def protected_commit():
    assert all(file.owner=='Administrator' for file in files.values()),'Unprotected File became visible at commit'
frappe.db=types.SimpleNamespace(get_value=lambda *args:next((file.name for file in files.values() if file.file_name==args[1]['file_name']),None),set_value=lambda kind,name,key,value,**kwargs:doc.__setattr__(key,value),commit=protected_commit)
cloud=types.ModuleType('zebra_erpnext.cloud');allowed=True
cloud.owned=lambda name,**kwargs:doc if name=='own' and allowed else frappe.throw('Denied')
sys.modules.update({'frappe':frappe,'zebra_erpnext.cloud':cloud,'redis':types.ModuleType('redis'),'redis.exceptions':types.SimpleNamespace(LockError=LockError)})
from zebra_erpnext import history as h,presentation as p
public=[dict(event_id='u',event_type='user_message_received',payload={'content':'question','attachments':[{'attachment_id':'att','message_event_id':'u','file_name':'in.txt','size_bytes':2,'secret':'hidden'}]}),dict(event_id='a',event_type='answer_committed',payload={'assistant_message':'legacy body','parts':[dict(id='text',type='text',text='complete visible body',format='markdown')], 'sources':[{'title':'source','url':'https://example.com'},{'title':'bad','url':'javascript:alert(1)'}]})]
calls=[]
h.load=lambda doc:(calls.append('GET public history') or {},public)
message=h.messages(public)[-1];digest=message['digest'];args=('own','a',digest)
assert h.body_text(message)=='complete visible body'
assert h.messages(public)[0]['attachments']==[dict(attachment_id='att',file_name='in.txt',size_bytes=2)]
assert len(message['sources'])==1
first=p.save(*args,report=True);second=p.save(*args,report=True)
assert first==second and len(files)==1 and files['file-0'].owner=='Administrator' and files['file-0'].is_private
assert owner_updates==['file-0'], 'Service ownership was not assigned exactly once before commit'
assert b'complete visible body' in p.download(*args) and b'legacy body' not in p.download(*args)
assert 'report_file' not in first and 'file_url' not in json.dumps(first)
assert p.save(*args,feedback='helpful')['feedback']=='helpful'
assert p.decorate(doc,h.messages(public))[-1]['report_saved']
def rejects(fn):
    try:fn()
    except Rejected:return
    raise AssertionError('Expected denial')
for fn in (lambda:p.save('other','a',digest,report=True),lambda:p.download('other','a',digest)):
    before=len(calls);rejects(fn);assert len(calls)==before
allowed=False;rejects(lambda:p.download(*args));rejects(lambda:p.save(*args,report=True));allowed=True
rejects(lambda:p.save('own','a','0'*64,report=True));rejects(lambda:p.save('own','u',digest,report=True));rejects(lambda:p.save(*args,feedback='write'))
with Lock('zebra:submit:own'):rejects(lambda:p.save(*args,report=True))
files['file-0'].owner='user';rejects(lambda:p.download(*args));files['file-0'].owner='Administrator'
files['file-0'].content=b'tampered';rejects(lambda:p.save(*args,report=True))
print('PASS full public answer binding, text-parts body, metadata allowlist, report/feedback persistence and idempotency, service File owner, shared submit lock, live ownership/company denial and tamper rejection')

# Truncation must disable mutations for raw rich text, explicit part count and
# aggregate public deliveries, including answers with no legacy content.
original_public=public
text_part=lambda index,text='body':dict(id='text-'+str(index),type='text',format='plain',text=text)
file_part=lambda index:dict(id='file-'+str(index),type='file',artifactId='artifact-'+str(index),mimeType='text/plain',fileName='file-'+str(index)+'.txt')
cases=[
 [dict(event_id='long-rich',event_type='answer_committed',payload={'parts':[text_part(0,'x'*100001)]})],
 [dict(event_id='many-rich',event_type='answer_committed',payload={'parts':[text_part(i) for i in range(17)]})],
 [*[dict(event_type='tool_execution_completed',payload={'metadata':{'delivery':True,'schema_version':'2','content_parts':[file_part(i) for i in range(start,start+6)]}}) for start in (0,6,12)],dict(event_id='aggregate-rich',event_type='answer_committed',payload={'assistant_message':''})],
]
for public in cases:
    projected=h.messages(public)[-1]
    assert projected['content_truncated'] and len(projected['parts'])<=16
    before=(len(files),doc.presentation_json)
    for mutation in (lambda:p.save('own',projected['id'],projected['digest'],report=True),lambda:p.save('own',projected['id'],projected['digest'],feedback='helpful')):rejects(mutation)
    assert (len(files),doc.presentation_json)==before
print('PASS oversized rich text, oversized parts-only arrays and aggregate tool-delivery truncation reject both report and feedback')

# Copy/visible body and saved report must use the same public URI placeholder in
# legacy Markdown and plain-text Parts. Private native coordinates stay hidden.
for index,payload in enumerate(({'assistant_message':'[报告](artifact://private-id) Markdown'}, {'parts':[text_part(0,'plain artifact://private-id text')]})):
    public=[dict(event_id='uri-'+str(index),event_type='answer_committed',payload=payload)]
    projected=h.messages(public)[-1]
    expected='[报告](（成果见文件区）) Markdown' if index==0 else 'plain （成果见文件区） text'
    assert h.body_text(projected)==expected
    coordinates=('own',projected['id'],projected['digest'])
    p.save(*coordinates,report=True)
    downloaded=p.download(*coordinates);text=downloaded.decode() if isinstance(downloaded,bytes) else downloaded
    assert text.endswith(expected) and 'artifact://' not in text
public=original_public
print('PASS Markdown/plain-part public body and report download share artifact-coordinate masking')

# Exercise the actual snapshot RPC body with tiny transport/decorator doubles.
# A known rejection is a receipt even before a native Task was created; a pinned
# command remains unknown and must never publish a rejection receipt.
frappe.whitelist=lambda **kwargs:lambda function:function
sys.modules['zebra_erpnext.chat']=types.ModuleType('zebra_erpnext.chat')
sys.modules['werkzeug.wrappers']=types.SimpleNamespace(Response=lambda *args,**kwargs:None)
from zebra_erpnext import api
for task_id in (None,'task'):
    doc.task_id=task_id;doc.request_id='known-rejection';doc.status='rejected';doc.pending_command=None
    assert api.snapshot('own')['rejected_request_id']=='known-rejection'
    doc.pending_command='pinned unknown command'
    assert api.snapshot('own')['rejected_request_id'] is None
    doc.pending_command=None;doc.status='dispatching'
    assert api.snapshot('own')['rejected_request_id'] is None
    doc.status='running'
    snapshot=api.snapshot('own')
    assert snapshot['rejected_request_id'] is None
    if task_id:assert snapshot['accepted_request_id']=='known-rejection'
print('PASS snapshot rejection receipts before/after Task creation, accepted receipt and unknown-command fail-closed projection')
