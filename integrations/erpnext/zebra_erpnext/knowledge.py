"""Private, company-scoped source documents and Native governed memory management."""
import base64
import json
from urllib.parse import quote

import frappe
from zebra_erpnext import cloud, runtime
from zebra_erpnext.resources import validate_attachments


def require(conversation):
    doc = cloud.owned(conversation)
    if not runtime.enabled(doc, cloud.config(), 'knowledge'):
        frappe.throw('此会话尚未开放知识资料和记忆')
    return doc


def source(doc, name):
    value = frappe.get_doc('Zebra Knowledge', name)
    if value.user != doc.user or value.company != doc.company or value.status != 'active':
        frappe.throw('知识资料不存在', frappe.PermissionError)
    file = frappe.get_doc('File', value.file_id)
    if (not file.is_private or file.owner != 'Administrator' or file.attached_to_doctype != 'Zebra Knowledge'
            or file.attached_to_name != value.name):
        frappe.throw('知识资料附件归属不匹配', frappe.PermissionError)
    return value, file


def inventory(conversation):
    doc = require(conversation)
    rows = frappe.get_all('Zebra Knowledge',
        filters={'user': doc.user, 'company': doc.company, 'status': 'active'},
        fields=['name', 'title', 'media_type', 'modified'], order_by='modified desc', limit_page_length=100)
    return {'sources': rows, 'selected': [item for item in runtime.preferences(doc).get('knowledge_ids', [])
        if item in {row.name for row in rows}]}


def create(conversation, title, attachment):
    doc = require(conversation)
    if not isinstance(title, str) or not 0 < len(title.strip()) <= 120:
        frappe.throw('资料名称须为 1 到 120 个字符')
    if frappe.db.count('Zebra Knowledge', {'user': doc.user, 'company': doc.company, 'status':'active'}) >= 100:
        frappe.throw('每个用户与公司最多保存 100 份资料')
    item = frappe.parse_json(attachment) if isinstance(attachment, str) else attachment
    accepted = validate_attachments([item], 'deepseek-v4-flash-executor-v1')[0]
    record = frappe.get_doc({'doctype':'Zebra Knowledge', 'title':title.strip(), 'user':doc.user,
        'company':doc.company, 'media_type':accepted['media_type'], 'status':'active'})
    record.db_insert()
    file = frappe.get_doc({'doctype':'File', 'file_name':accepted['file_name'], 'is_private':1,
        'attached_to_doctype':'Zebra Knowledge', 'attached_to_name':record.name,
        'content':base64.b64decode(accepted['content_base64'], validate=True)}).insert(ignore_permissions=True)
    # Reuse the report storage boundary: a user-owned File bypasses company
    # checks through Frappe's direct download permission path.
    file.db_set('owner', 'Administrator', update_modified=False, commit=False)
    record.file_id = file.name
    record.db_update()
    return {'name':record.name, 'title':record.title}


def remove(conversation, name):
    doc = require(conversation)
    record, _ = source(doc, name)
    # Keep the immutable originals referenced by previous Task snapshots. Tombstone
    # this library entry; future selection/materialization cannot read it.
    frappe.db.set_value('Zebra Knowledge', record.name, 'status', 'deleted')
    return {'deleted':True}


def select(conversation, source_ids):
    from redis.exceptions import LockError
    require(conversation)
    ids = frappe.parse_json(source_ids) if isinstance(source_ids, str) else source_ids
    if not isinstance(ids, list) or len(ids) > 4 or any(not isinstance(item, str) for item in ids) or len(set(ids)) != len(ids):
        frappe.throw('最多选择 4 份知识资料')
    try:
        with frappe.cache.lock('zebra:submit:' + conversation, timeout=180, blocking_timeout=0) as lock:
            doc = cloud.owned(conversation, for_update=True, admission_lock=lock)
            if doc.status in {'running', 'dispatching'} or doc.pending_command:
                frappe.throw('当前任务执行中，请结束后调整资料')
            for item in ids:
                source(doc, item)
            prefs = runtime.preferences(doc)
            prefs['knowledge_ids'] = ids
            frappe.db.set_value('Zebra Conversation', doc.name, 'preferences_json', json.dumps(prefs), update_modified=False)
            frappe.db.commit()
            return {'selected':ids}
    except LockError:
        frappe.throw('会话正在提交，请稍后调整资料')


def materialize(doc):
    ids = runtime.preferences(doc).get('knowledge_ids', [])
    if not ids:
        return []
    require(doc.name)
    if not isinstance(ids, list) or len(ids) > 4:
        frappe.throw('知识资料选择超限')
    files = []
    for item in ids:
        record, file = source(doc, item)
        if type(file.file_size) not in (int, float) or not 0 <= file.file_size <= 16777216:
            frappe.throw('知识资料文件超过安全上限')
        payload = file.get_content()
        payload = payload.encode('utf-8') if isinstance(payload, str) else payload
        files.append({'file_name':file.file_name, 'media_type':record.media_type,
                      'content_base64':base64.b64encode(payload).decode('ascii')})
    return files


def memory(conversation, action='list', text=None, memory_id=None, revision=None):
    doc = require(conversation)
    path = '/users/' + quote(doc.user, safe='') + '/memory'
    if action == 'list':
        return cloud.request(doc, 'GET', path)
    if not doc.task_id:
        frappe.throw('请先完成一次任务，再保存有来源的记忆')
    body = {'operator':doc.user, 'reason':'user memory management from ERP'}
    if action == 'create':
        body.update(text=text, source_task_id=doc.task_id)
        return cloud.request(doc, 'POST', path, body=body)
    from zebra_erpnext.extensions import identifier
    path += '/' + identifier(memory_id)
    # Native reads the authoritative revision and commits with its existing CAS.
    if action == 'replace':
        return cloud.request(doc, 'PATCH', path, body={**body, 'text':text})
    if action == 'delete':
        return cloud.request(doc, 'DELETE', path, body=body)
    frappe.throw('记忆操作无效')
