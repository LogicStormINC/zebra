"""Private answer bookmarks and feedback; execution remains native Cloud work."""
import hashlib
import json
import re

import frappe
from zebra_erpnext import cloud, history


def _read(doc):
    value = json.loads(doc.get('presentation_json') or '{}')
    if not isinstance(value, dict) or len(json.dumps(value)) > 262144:
        frappe.throw('会话展示记录无效，请联系管理员核对')
    return value


def decorate(doc, messages):
    records = _read(doc)
    for message in messages:
        record = records.get(message.get('digest'), {})
        if record.get('message_id') == message['id']:
            message['feedback'] = record.get('feedback')
            message['report_saved'] = bool(record.get('report_file'))
    return messages


def _coordinates(message_id, digest):
    if not isinstance(message_id, str) or not 1 <= len(message_id) <= 200 or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        frappe.throw('回答标识无效')


def _message(doc, message_id, digest):
    _coordinates(message_id, digest)
    _, events = history.load(doc)
    message = next((row for row in history.messages(events) if row['id'] == message_id and row.get('digest') == digest and row['role'] == 'assistant'), None)
    if not message or message.get('content_truncated'):
        frappe.throw('回答不在当前可核对的完整公开记录中，请重新连接后重试')
    return message


def _file(doc, record):
    file = frappe.get_doc('File', record['report_file'])
    if not file.is_private or file.owner != 'Administrator' or file.attached_to_doctype != 'Zebra Conversation' or file.attached_to_name != doc.name:
        frappe.throw('报告归属不匹配', frappe.PermissionError)
    return file


def save(conversation, message_id, digest, feedback=None, *, report=False):
    from redis.exceptions import LockError
    cloud.owned(conversation)
    _coordinates(message_id, digest)
    if not report and feedback not in {'helpful', 'unhelpful'}:
        frappe.throw('反馈选项无效')
    try:
        # Grant issuance commits while reading Cloud. Reuse submit admission so
        # no stale Doc.db_update can overwrite this additive presentation field.
        with frappe.cache.lock('zebra:submit:' + conversation, timeout=180, blocking_timeout=0) as admission_lock:
            doc = cloud.owned(conversation)
            message = _message(doc, message_id, digest)
            doc = cloud.owned(conversation, for_update=True, admission_lock=admission_lock)
            records = _read(doc)
            if digest not in records and len(records) >= 100:
                frappe.throw('本会话已达到 100 条报告与反馈记录上限，请新建会话')
            record = records.setdefault(digest, {'message_id': message_id})
            if report:
                content = ('# Zebra ERP 工作报告\n\n公司：' + doc.company + '\n\n会话：' + doc.name + '\n\n回答标识：' + message_id + '\n\n---\n\n' + history.body_text(message)).encode('utf-8')
                if record.get('report_file'):
                    file = _file(doc, record)
                else:
                    # Deterministic native File coordinates recover an acknowledged
                    # File insert even if its presentation acknowledgement was lost.
                    filename = 'zebra-report-' + hashlib.sha256((doc.user + '\0' + doc.company + '\0' + doc.name + '\0' + digest).encode()).hexdigest() + '.md'
                    existing = frappe.db.get_value('File', {'file_name': filename, 'owner': 'Administrator', 'is_private': 1, 'attached_to_doctype': 'Zebra Conversation', 'attached_to_name': doc.name}, 'name')
                    # Frappe grants File owners direct access before checking the
                    # attached document. A service owner keeps ordinary retrieval
                    # behind this RPC's live company/conversation authorization.
                    if existing:
                        file = _file(doc, {'report_file': existing})
                    else:
                        file = frappe.get_doc(dict(doctype='File', file_name=filename, content=content, is_private=1, attached_to_doctype='Zebra Conversation', attached_to_name=doc.name)).insert(ignore_permissions=True)
                        # Native insert stamps the session owner. db_set changes
                        # both this document and its row before either is committed.
                        file.db_set('owner', 'Administrator', update_modified=False, commit=False)
                actual = file.get_content()
                if (actual.encode('utf-8') if isinstance(actual, str) else actual) != content:
                    frappe.throw('已有报告内容与公开回答不匹配，请联系管理员核对')
                record['report_file'] = file.name
            else:
                record['feedback'] = feedback
            frappe.db.set_value('Zebra Conversation', conversation, 'presentation_json', json.dumps(records, ensure_ascii=False), update_modified=False)
            frappe.db.commit()  # publish the File and its idempotency record before releasing admission
            return dict(message_id=message_id, digest=digest, feedback=record.get('feedback'), report_saved=bool(record.get('report_file')))
    except LockError:
        frappe.throw('会话正在提交，请稍后保存报告或反馈')


def download(conversation, message_id, digest):
    doc = cloud.owned(conversation)
    _coordinates(message_id, digest)
    record = _read(doc).get(digest, {})
    if record.get('message_id') != message_id or not record.get('report_file'):
        frappe.throw('尚无已保存的报告')
    return _file(doc, record).get_content()
