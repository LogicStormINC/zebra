"""Private scheduler workload exchange; every firing rechecks current ERP authority."""
import hashlib
import hmac
import json
import time
from uuid import UUID

import frappe
from zebra_erpnext import cloud, runtime

FIELDS = {'audience','threadId','runId','scopes','resourceRefs','principal'}


def verified_request(body, headers, settings, now=None):
    """Pure signature/wire boundary; no SQL, model or search activity."""
    secret = settings.get('schedule_workload_secret')
    identity = settings.get('schedule_workload_identity', 'erpnext-scheduler-full')
    timestamp, nonce = headers.get('X-Zebra-Workload-Timestamp',''), headers.get('X-Zebra-Workload-Nonce','')
    if (not secret or not isinstance(body,dict) or set(body)!=FIELDS
            or headers.get('X-Zebra-Workload-Identity')!=identity
            or not timestamp.isascii() or not timestamp.isdecimal() or len(timestamp)>11
            or abs((time.time() if now is None else now)-int(timestamp))>30
            or body.get('audience')!='zebra' or nonce!=body.get('runId')):
        raise ValueError('scheduler authority rejected')
    if str(UUID(body['runId']))!=body['runId'] or str(UUID(body['threadId']))!=body['threadId']:
        raise ValueError('noncanonical scheduler identity')
    canonical=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    if len(canonical.encode())>32768:
        raise ValueError('scheduler request exceeds budget')
    digest=hashlib.sha256(canonical.encode()).hexdigest()
    signature=hmac.new(secret.encode(),f'{timestamp}\n{nonce}\n{digest}'.encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature,headers.get('X-Zebra-Workload-Signature','')):
        raise ValueError('scheduler signature rejected')
    refs=body.get('resourceRefs')
    if (not isinstance(refs,list) or len(refs)!=2 or any(not isinstance(r,dict) or set(r)!={'type','id'}
            or not isinstance(r['id'],str) or not 0<len(r['id'])<=512 for r in refs)):
        raise ValueError('scheduler resource scope rejected')
    mapped={r['type']:r['id'] for r in refs}
    if set(mapped)!={'company','schedule_request'}:
        raise ValueError('scheduler resource scope rejected')
    principal=body.get('principal')
    if not isinstance(principal,dict) or set(principal)!={'userId','workspaceId'}:
        raise ValueError('scheduler principal rejected')
    scopes=body.get('scopes')
    if not isinstance(scopes,list) or len(scopes)>32 or any(not isinstance(v,str) for v in scopes):
        raise ValueError('scheduler scopes rejected')
    return mapped


def exchange():
    request=frappe.local.request
    body=request.get_json(silent=True)
    base=cloud.config()
    candidate=(base.get('runtimes') or {}).get(runtime.FULL) or {}
    try:
        refs=verified_request(body,request.headers,candidate)
    except (ValueError,TypeError,KeyError,AttributeError):
        frappe.throw('调度工作负载未授权',frappe.PermissionError)
    record=frappe.get_doc('Zebra Schedule',refs['schedule_request'])
    if record.status not in {'creating','active'} or record.runtime_ref!=runtime.FULL or record.company!=refs['company']:
        frappe.throw('计划已暂停、删除或撤销',frappe.PermissionError)
    old_user=frappe.session.user
    try:
        frappe.set_user(record.user)
        source=cloud.owned(record.conversation)
        settings=runtime.settings(source,base)
        if not runtime.enabled(source,base,'schedules'):
            frappe.throw('调度已停用',frappe.PermissionError)
        if (record.company!=source.company or record.user!=source.user
                or body['principal']!={'userId':source.user,'workspaceId':source.workspace_ref}
                or not set(body['scopes'])<=set(settings['scopes'])
                or not {'agent.run','erpnext.read'}<=set(body['scopes'])):
            frappe.throw('调度权限已变化',frappe.PermissionError)
        if record.native_id and record.native_id!=body['threadId']:
            frappe.throw('计划身份冲突',frappe.PermissionError)
        from redis.exceptions import LockError
        try:
            with frappe.cache.lock('zebra:schedule-exchange:'+body['runId'],timeout=30,blocking_timeout=0):
                current=frappe.get_doc('Zebra Schedule',record.name,for_update=True)
                if current.status not in {'creating','active'} or current.native_id not in (None,'',body['threadId']):
                    frappe.throw('计划已撤销或身份变化',frappe.PermissionError)
                # Only this authenticated scheduler may bind a committed Native
                # identity after its create response was lost. Browser input cannot.
                frappe.db.set_value('Zebra Schedule',record.name,{'native_id':body['threadId'],'status':'active'})
                name='zsf_'+hashlib.sha256((record.name+'\0'+body['runId']).encode()).hexdigest()[:40]
                if frappe.db.exists('Zebra Conversation',name):
                    conversation=frappe.get_doc('Zebra Conversation',name)
                    if (conversation.schedule_ref!=record.name or conversation.user!=record.user
                            or conversation.company!=record.company or conversation.active_run_id!=body['runId']):
                        frappe.throw('计划执行身份冲突',frappe.PermissionError)
                else:
                    conversation=frappe.get_doc({'doctype':'Zebra Conversation','name':name,
                        'user':record.user,'company':record.company,'title':record.title[:120],
                        'host_thread':body['threadId'],'workspace_ref':source.workspace_ref,
                        'active_run_id':body['runId'],'status':'dispatching','runtime_ref':runtime.FULL,
                        'schedule_ref':record.name,'schedule_fire_id':body['runId'],
                        'preferences_json':record.preferences_json})
                    conversation.db_insert()
                token=cloud.grant(conversation,body['runId'],authority_refs=[{'type':'schedule_request','id':record.name}])
        except LockError:
            frappe.throw('计划授权正在核对，请稍后恢复')
        from zebra_erpnext.gateway import raw
        return raw({'grant':token})
    finally:
        frappe.set_user(old_user)


def bind_execution(conversation, record, arguments):
    """Hidden signed Worker control only; no model-visible business dispatch."""
    if not getattr(conversation,'schedule_ref',None):
        return conversation
    conversation=frappe.get_doc('Zebra Conversation',conversation.name,for_update=True)
    if not runtime.enabled(conversation,cloud.config(),'schedules'):
        frappe.throw('调度授权已撤销',frappe.PermissionError)
    runtime.profile(conversation,cloud.config())
    schedule=frappe.get_doc('Zebra Schedule',conversation.schedule_ref)
    if (schedule.status!='active' or schedule.user!=record.user or schedule.company!=record.company
            or schedule.native_id!=conversation.host_thread
            or conversation.schedule_fire_id!=record.run_id):
        frappe.throw('计划执行已暂停或撤销',frappe.PermissionError)
    if not conversation.task_id:
        identity=str(UUID(arguments['task_id']))
        frappe.db.set_value('Zebra Conversation',conversation.name,'task_id',identity)
        conversation.task_id=identity
    elif conversation.task_id!=arguments['task_id']:
        frappe.throw('计划任务身份冲突',frappe.PermissionError)
    return conversation
