"""Run only in capability-qa.local: actual Frappe/TLS/Native/S3 RPCs, no model/Worker."""
import base64
import io
import json
from pathlib import Path
import re
import secrets
from uuid import uuid4
from zipfile import ZipFile

import frappe
import requests
from zebra_erpnext import cloud,chat,runtime


def run():
    if frappe.local.site!='capability-qa.local' or cloud.config()['issuer']!='https://erpnext-full-qa.zebra.local':
        raise ValueError('dedicated cloned site required')
    frappe.set_user('Administrator')
    password=secrets.token_urlsafe(32)
    from frappe.utils.password import update_password
    update_password('Administrator',password)
    frappe.db.commit()
    credentials=Path('/tmp/full-qa-login.json');credentials.write_text(json.dumps(dict(user='Administrator',password=password)));credentials.chmod(0o600)
    results=[]
    state={'model_calls':0,'search_calls':0,'worker_started':False,'checks':results}
    output=Path('/tmp/full-capability-host-check.json')
    def checkpoint():output.write_text(json.dumps(state,indent=2));output.chmod(0o600)
    checkpoint()
    session=requests.Session();session.verify=cloud.config()['ca_file'];session.trust_env=False
    base='https://erpnext-full-qa.zebra.local'
    response=session.post(base+'/api/method/login',json={'usr':'Administrator','pwd':password},timeout=15);response.raise_for_status()
    page=session.get(base+'/app',timeout=20);page.raise_for_status()
    token=re.search(r'frappe\.csrf_token\s*=\s*[\'"]([^\'"]+)',page.text).group(1)
    session.headers.update({'X-Frappe-CSRF-Token':token,'Origin':cloud.config()['origin']})
    def rpc(method,args=None):
        response=session.post(base+'/api/method/zebra_erpnext.api.'+method,json=args or {},timeout=30)
        if response.status_code!=200:
            # Server traceback stays in the private QA container log; only finite method/status here.
            raise AssertionError((method,response.status_code,response.json().get('exception')))
        value=response.json()
        if value.get('exc'):raise AssertionError((method,'business_error'))
        return value['message']
    company=frappe.db.get_single_value('Global Defaults','default_company')
    conversation=rpc('create_conversation',{'title':'FULL-CAPABILITY-QA-'+uuid4().hex[:8],'company':company})
    name=conversation['name'];state['conversation']=name;checkpoint()
    catalog=rpc('capability_catalog',{'conversation':name})
    assert catalog['runtime_release']=='cloud114' and catalog['runtime']['status']=='available',catalog['runtime']
    assert all(g['status']=='available' for g in catalog['groups'] if g['id']!='erp'),catalog['groups']
    results.append('actual runtime capability discovery');checkpoint()
    attachment=dict(file_name='qa-private.txt',media_type='text/plain',content_base64=base64.b64encode(b'Only isolated QA evidence.').decode())
    source=rpc('knowledge_create',{'conversation':name,'title':'Private QA note','attachment':json.dumps(attachment)})
    rpc('knowledge_select',{'conversation':name,'source_ids':json.dumps([source['name']])})
    listing=rpc('knowledge_inventory',{'conversation':name})
    assert listing['selected']==[source['name']] and any(row['name']==source['name'] for row in listing['sources'])
    results.append('private File-backed knowledge persists and selection restores');checkpoint()
    data=io.BytesIO()
    with ZipFile(data,'w') as archive:archive.writestr('SKILL.md','---\nname: qa-private-guide-'+uuid4().hex[:8]+'\ndescription: Isolated guide\nversion: v1\n---\nRead only the isolated QA note.')
    installed=rpc('skill_import',{'conversation':name,'content_base64':base64.b64encode(data.getvalue()).decode(),'request_id':'qa-'+uuid4().hex})
    skill=installed['installation_id']
    if not installed['enabled']:
        installed=rpc('extension_toggle',{'conversation':name,'kind':'skills','item':skill,'expected_revision':installed['revision'],'enabled':True})
    rpc('configure_capabilities',{'conversation':name,'capability_profile':'analysis','selection':json.dumps({'skills':[skill],'mcp':[]})})
    fresh=rpc('extension_inventory',{'conversation':name,'kind':'skills'})
    assert any(item['installation_id']==skill and item['enabled'] for item in fresh['items'])
    results.append('real zip publication and versioned S3 Skill install/enable/selection');checkpoint()
    key=str(uuid4())
    mcp=rpc('extension_create',{'conversation':name,'kind':'mcp','request_id':key,'endpoint':'https://example.invalid/mcp','auth_mode':'bearer'})
    again=rpc('extension_create',{'conversation':name,'kind':'mcp','request_id':key,'endpoint':'https://example.invalid/mcp','auth_mode':'bearer'})
    assert mcp['connection_id']==again['connection_id'] and not mcp['enabled']
    saved=rpc('extension_credentials',{'conversation':name,'item':mcp['connection_id'],'expected_revision':mcp['revision'],'token':'isolated-qa-token-not-an-external-credential'})
    assert 'isolated-qa-token' not in json.dumps(saved)
    results.append('MCP config create idempotency and encrypted credential storage; no endpoint call');checkpoint()
    schedule=rpc('schedule_create',{'conversation':name,'title':'Future QA only','prompt':'Read isolated evidence without changing business data',
        'trigger':json.dumps({'kind':'once','fire_at':'2099-01-01T00:00:00Z'}),'request_id':str(uuid4())})
    identity=schedule['name'];state['schedule']=identity;checkpoint()
    detail=rpc('schedule_detail',{'conversation':name,'name':identity})
    assert detail['status']=='active'
    paused=rpc('schedule_action',{'conversation':name,'name':identity,'operation':'pause','schedule_version':detail['schedule_version']})
    assert paused['status']=='paused'
    restored=rpc('schedule_detail',{'conversation':name,'name':identity});assert restored['status']=='paused'
    results.append('Native future schedule persists and pause restores; never fired');checkpoint()
    # This operator-only fixture creates a prepared Task, without dispatching any Run.
    frappe.db.rollback()  # Refresh the CLI transaction after independently committed HTTP requests.
    doc=cloud.owned(name);run_id=str(uuid4())
    frappe.db.set_value('Zebra Conversation',name,{'active_run_id':run_id,'status':'dispatching'})
    frappe.db.commit();doc=cloud.owned(name)
    from zebra_erpnext import extensions,knowledge
    task=cloud.request(doc,'POST','/tasks',run_id=run_id,key='qa-task-'+name,body=dict(prompt='Read isolated QA material',title='Isolated prepared task',execute=False,
        interaction_mode='conversation',history_session_ids=[],attachments=knowledge.materialize(doc),
        **chat.saved_options(doc),**runtime.profile(doc,cloud.config()),skill_components=extensions.task_skills(doc),
        workspace_source=dict(kind='host_reference',locator='erpnext://workspace/'+name)))
    frappe.db.set_value('Zebra Conversation',name,{'task_id':task['task_id'],'status':'running'})
    frappe.db.commit();state.update(task_id=task['task_id'],run_id=run_id,task=task);checkpoint()
    headers=rpc('artifact_segments',{'conversation':name})
    assert headers
    rpc('memory_manage',{'conversation':name,'action':'create','text':'Use the isolated QA workspace only.'})
    memories=rpc('memory_manage',{'conversation':name});assert any(m['text']=='Use the isolated QA workspace only.' for m in memories['memories'])
    results.append('prepared Task attachment admission, historical index and scoped Native Memory persistence');checkpoint()
    print(json.dumps(dict(stage='qa_host_checks_complete',checks=results,conversation=name,task_id=task['task_id'],model_calls=0,search_calls=0),ensure_ascii=False))


def prepare_saved(conversation):
    if frappe.local.site!='capability-qa.local':raise ValueError('QA only')
    frappe.set_user('Administrator')
    doc=cloud.owned(conversation)
    if not doc.title.startswith('FULL-CAPABILITY-QA-') or doc.task_id:
        raise ValueError('fresh isolated fixture required')
    name=conversation
    state={'conversation':name,'model_calls':0,'search_calls':0,'worker_started':False}
    def checkpoint():Path('/tmp/full-capability-prepared-check.json').write_text(json.dumps(state,indent=2))
    # This operator-only fixture creates a prepared Task, without dispatching any Run.
    frappe.db.rollback()  # Refresh the CLI transaction after independently committed HTTP requests.
    doc=cloud.owned(name);run_id=str(uuid4())
    frappe.db.set_value('Zebra Conversation',name,{'active_run_id':run_id,'status':'dispatching'})
    frappe.db.commit();doc=cloud.owned(name)
    from zebra_erpnext import extensions,knowledge
    task=cloud.request(doc,'POST','/tasks',run_id=run_id,key='qa-task-'+name,body=dict(prompt='Read isolated QA material',title='Isolated prepared task',execute=False,
        interaction_mode='conversation',history_session_ids=[],attachments=knowledge.materialize(doc),
        **chat.saved_options(doc),**runtime.profile(doc,cloud.config()),skill_components=extensions.task_skills(doc),
        workspace_source=dict(kind='host_reference',locator='erpnext://workspace/'+name)))
    frappe.db.set_value('Zebra Conversation',name,{'task_id':task['task_id'],'status':'running'})
    frappe.db.commit();state.update(task_id=task['task_id'],run_id=run_id,task=task);checkpoint()
    print(json.dumps(state))


def prepare_fresh_from_saved(conversation):
    if frappe.local.site!='capability-qa.local':raise ValueError('QA only')
    frappe.set_user('Administrator')
    old=cloud.owned(conversation)
    if not old.title.startswith('FULL-CAPABILITY-QA-'):raise ValueError('isolated fixture required')
    new=chat.create('FULL-CAPABILITY-QA-'+uuid4().hex[:8],old.company)
    frappe.db.set_value('Zebra Conversation',new['name'],'preferences_json',old.preferences_json)
    frappe.db.commit()
    return prepare_saved(new['name'])
