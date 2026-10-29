"""Run python3 tests/test_workspace_checks.py; no real crypto, network or DB writes."""
import base64
import json
from pathlib import Path
import sys
import types
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
frappe=types.ModuleType('frappe');utils=types.ModuleType('frappe.utils')
class Rejected(Exception):pass
frappe.throw=lambda text,*args:(_ for _ in ()).throw(Rejected(text))
frappe.PermissionError=Rejected
frappe.ValidationError=Rejected
frappe.local=types.SimpleNamespace(site='erp.test')
frappe.session=types.SimpleNamespace(user='alice')
frappe.conf={'zebra_agent':{'enabled':True,'base_url':'https://cloud.invalid','issuer':'erp-test','origin':'https://erp.invalid','signing_key':'/unused','ca_file':'/unused','host_secret':'unused'}}
frappe.db=types.SimpleNamespace(get_value=lambda *a,**k:1,commit=lambda:None)
company=types.SimpleNamespace(check_permission=lambda *a:None)
frappe.get_doc=lambda *a,**k: company if len(a)>1 else types.SimpleNamespace(db_insert=lambda:None)
from datetime import datetime
utils.now_datetime=datetime.now
sys.modules.update({'frappe':frappe,'frappe.utils':utils})
try:import requests
except ImportError:sys.modules['requests']=types.ModuleType('requests')
from zebra_erpnext import cloud
cloud.subprocess.run=lambda *a,**k:types.SimpleNamespace(stdout=b'signature')

def doc(ref=None,task=None):
 return types.SimpleNamespace(name='c',user='alice',company='Co',workspace_ref=ref,task_id=task,host_thread='thread',db_update=lambda:None)
first=cloud.private_workspace_ref('alice','Co')
assert first.startswith('erp-u-') and first.isascii()
assert first==cloud.private_workspace_ref('alice','Co')
assert first!=cloud.private_workspace_ref('bob','Co')
assert first!=cloud.private_workspace_ref('alice','Other')
frappe.local.site='other.test';assert first!=cloud.private_workspace_ref('alice','Co');frappe.local.site='erp.test'
fresh=doc();token=cloud.grant(fresh)
assert fresh.workspace_ref==first and cloud.has_private_workspace(fresh)
claims=json.loads(base64.urlsafe_b64decode(token.split('.')[1]+'=='))
assert claims['workspace_ref']==first and 'artifact.read' in claims['scopes']
legacy=doc('erp-old-company','old-task');cloud.grant(legacy)
assert legacy.workspace_ref=='erp-old-company' and not cloud.has_private_workspace(legacy)
try:cloud.grant(doc(task='old-task'))
except Rejected:pass
else:raise AssertionError('Missing legacy Task workspace was silently rebound')
print('PASS user/company/site workspace isolation, pinned legacy binding and artifact read grant')

settings=frappe.conf["zebra_agent"];settings["admission_paused"]=True
cloud.requests.request=lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError("Paused mutation reached HTTP"))
for method in ("POST","PATCH","DELETE"):
 try:cloud.request(fresh,method,"/must-not-mutate")
 except Rejected as e:assert "维护" in str(e)
 else:raise AssertionError("Paused Cloud mutation accepted")
settings["admission_paused"]=False;cloud.require_admission_open()
print("PASS shared maintenance guard blocks Cloud mutations before issuing grants or HTTP")
