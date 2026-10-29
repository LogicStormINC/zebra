"""Fixed Native extension RPCs with scoped grants, CAS and frozen root selections."""
import json
import re

import frappe
from zebra_erpnext import cloud, runtime

KINDS = {'skills': 'skill-installations', 'mcp': 'mcp-connections'}


def require(conversation):
    doc = cloud.owned(conversation)
    if not runtime.enabled(doc, cloud.config(), 'extensions'):
        frappe.throw('此会话尚未开放技能和连接；请使用已升级的新会话')
    return doc


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', value):
        frappe.throw('扩展标识无效')
    return value


def path(kind, item=None):
    if kind not in KINDS:
        frappe.throw('扩展类别无效')
    return '/v1/extensions/' + KINDS[kind] + ('/' + identifier(item) if item else '')


def revision(value):
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        frappe.throw('扩展版本无效，请刷新列表')
    return {'If-Match': '"%s"' % value}


def inventory(conversation, kind='skills', cursor=None):
    doc = require(conversation)
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 512):
        frappe.throw('扩展分页无效')
    return cloud.request(doc, 'GET', path(kind), params={'limit': '50', **({'cursor': cursor} if cursor else {})})


def configure(conversation, capability_profile='business', selection=None):
    from redis.exceptions import LockError
    require(conversation)
    try:
        with frappe.cache.lock('zebra:submit:' + conversation, timeout=180, blocking_timeout=0) as lock:
            doc = cloud.owned(conversation, for_update=True, admission_lock=lock)
            if doc.task_id or doc.pending_command or doc.status == 'dispatching':
                frappe.throw('运行能力已绑定此会话；请新建会话调整')
            candidate = frappe.parse_json(selection) if isinstance(selection, str) else selection or {}
            old = runtime.preferences(doc)
            updated = {**old, 'capability_profile': capability_profile, 'extension_selection': candidate}
            doc.preferences_json = json.dumps(updated)
            runtime.profile(doc, cloud.config())
            runtime.selections(doc)
            task_skills(doc)
            for item in candidate.get('mcp', []):
                entry = cloud.request(doc, 'GET', path('mcp', item))
                if entry.get('enabled') is not True or entry.get('selectable') is not True:
                    frappe.throw('MCP 尚未就绪，请先刷新工具目录')
            # grant issuance may commit; re-lock the current row and only write preferences.
            doc = cloud.owned(conversation, for_update=True, admission_lock=lock)
            if doc.task_id or doc.pending_command:
                frappe.throw('会话已开始，不能扩大运行能力')
            frappe.db.set_value('Zebra Conversation', conversation, 'preferences_json',
                                json.dumps(updated), update_modified=False)
            frappe.db.commit()
            return {'capability_profile': capability_profile, 'extension_selection': candidate}
    except LockError:
        frappe.throw('会话正在提交，请稍后调整')


def task_skills(doc):
    result = []
    for item in runtime.selections(doc).get('skills', []):
        entry = cloud.request(doc, 'GET', path('skills', item))
        if entry.get('installation_id') != item or entry.get('enabled') is not True:
            frappe.throw('所选 Skill 已停用或不可用')
        skill = (entry.get('version') or {}).get('skill_id')
        if not isinstance(skill, str) or not skill:
            frappe.throw('Skill 版本信息无效')
        if skill not in result:
            result.append(skill)
    return result


def toggle(conversation, kind, item, expected_revision, enabled):
    doc = require(conversation)
    if enabled not in (True, False, 'true', 'false', '0', '1', 0, 1):
        frappe.throw('启用状态无效')
    flag = enabled in (True, 'true', '1', 1)
    return cloud.request(doc, 'PATCH', path(kind, item), body={'enabled': flag},
                         extra_headers=revision(expected_revision))


def create(conversation, kind, request_id, endpoint=None, skill_id=None, version_id=None, auth_mode="none"):
    doc = require(conversation)
    key = 'erp-extension-' + identifier(request_id)
    if kind == 'mcp':
        if not isinstance(endpoint, str) or not 0 < len(endpoint) <= 2048:
            frappe.throw('请填写 MCP 服务地址')
        if auth_mode not in {'none', 'bearer'}:
            frappe.throw('MCP 认证类型无效')
        body = {'endpoint': endpoint, 'transport': 'streamable_http', 'auth_mode': auth_mode}
    elif kind == 'skills':
        body = {'skill_id': identifier(skill_id), 'version_id': identifier(version_id)}
    else:
        frappe.throw('扩展类别无效')
    return cloud.request(doc, 'POST', path(kind), body=body, key=key)


def refresh(conversation, item, expected_revision):
    return cloud.request(require(conversation), 'POST', path('mcp', item) + '/refresh',
                         extra_headers=revision(expected_revision))


def credentials(conversation, item, expected_revision, token=None):
    doc = require(conversation)
    if token is not None and (not isinstance(token, str) or not 0 < len(token) <= 4096
                              or any(not 0x21 <= ord(char) <= 0x7e for char in token)):
        frappe.throw('连接凭据格式无效')
    return cloud.request(doc, 'POST' if token is not None else 'DELETE',
        path('mcp', item) + '/credentials', body={'token': token} if token is not None else None,
        extra_headers=revision(expected_revision))


def import_skill(conversation, content_base64, request_id):
    from zebra_erpnext.resources import _decode
    doc = require(conversation)
    payload = _decode(content_base64, 10 * 1024 * 1024)
    published = cloud.request(doc, 'POST', '/v1/extensions/skill-packages',
        key='erp-skill-upload-' + identifier(request_id), content_bytes=payload,
        content_type='application/zip')
    return create(conversation, 'skills', request_id,
                  skill_id=published.get('skill_id'), version_id=published.get('version_id'))


def digest(value):
    if not isinstance(value, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}', value):
        frappe.throw('插件包标识无效')
    return value


def plugin_market(conversation, cursor=None):
    doc = require(conversation)
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 512):
        frappe.throw('插件分页无效')
    return cloud.request(doc, 'GET', '/v1/extensions/plugin-packages',
                         params={'limit': '50', **({'cursor': cursor} if cursor else {})})


def plugin_inventory(conversation, cursor=None):
    doc = require(conversation)
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 512):
        frappe.throw('插件分页无效')
    return cloud.request(doc, 'GET', '/v1/extensions/plugin-installations',
                         params={'limit': '50', **({'cursor': cursor} if cursor else {})})


def plugin_install(conversation, package_digest, request_id):
    doc = require(conversation)
    return cloud.request(doc, 'POST', '/v1/extensions/plugin-installations',
                         body={'package_digest': digest(package_digest)},
                         key='erp-plugin-' + identifier(request_id))


def plugin_toggle(conversation, installation, expected_revision, enabled):
    doc = require(conversation)
    if enabled not in (True, False, 'true', 'false', '0', '1', 0, 1):
        frappe.throw('启用状态无效')
    flag = enabled in (True, 'true', '1', 1)
    return cloud.request(doc, 'PATCH', '/v1/extensions/plugin-installations/' + identifier(installation),
                         body={'enabled': flag}, extra_headers=revision(expected_revision))
