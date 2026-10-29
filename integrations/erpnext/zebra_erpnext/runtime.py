"""Server-owned runtime releases and published capability profiles, never browser authority."""
import json
from urllib.parse import urlsplit

import frappe

LEGACY = 'native105'
FULL = 'cloud114'
PROFILES = {
    'business': dict(tool_profile='research', policy_profile='read_only', network_profile='none'),
    'research': dict(tool_profile='research', policy_profile='read_only', network_profile='full-gateway'),
    'analysis': dict(tool_profile='general', policy_profile='workspace_write', network_profile='full-gateway'),
}


def release(doc):
    value = getattr(doc, 'runtime_ref', None) or LEGACY
    if value not in {LEGACY, FULL}:
        frappe.throw('会话运行时无效；请联系管理员')
    return value


def settings(doc, base):
    if release(doc) == LEGACY:
        return base
    candidate = (base.get('runtimes') or {}).get(FULL)
    if not isinstance(candidate, dict) or candidate.get('enabled') is not True:
        frappe.throw('当前会话的 Cloud 运行时暂不可用；不会重新创建任务')
    result = {**base, **candidate}
    uri = urlsplit(str(result.get('base_url') or ''))
    if (uri.scheme != 'https' or not uri.hostname or uri.username or uri.password
            or uri.query or uri.fragment or result.get('namespace_id') != 'erpnext-full'):
        frappe.throw('Cloud 运行时配置无效')
    scopes = ['agent.run', 'erpnext.read', 'artifact.read']
    flags = result.get('capabilities') or {}
    if flags.get('extensions') is True:
        scopes += ['extensions.read', 'extensions.manage']
    if flags.get('knowledge') is True:
        scopes += ['memory.read', 'memory.write']
    if flags.get('schedules') is True:
        scopes += ['schedule.read', 'schedule.manage']
    result['scopes'] = sorted(scopes)
    return result


def new_release(base):
    candidate = (base.get('runtimes') or {}).get(FULL) or {}
    return FULL if candidate.get('enabled') is True and candidate.get('acceptance_passed') is True else LEGACY


def preferences(doc):
    value = json.loads(doc.preferences_json or '{}')
    if not isinstance(value, dict):
        frappe.throw('会话配置无效')
    return value


def profile(doc, base):
    if release(doc) == LEGACY:
        return dict(PROFILES['business'])
    config = settings(doc, base)
    selected = preferences(doc).get('capability_profile', 'business')
    allowed = config.get('capability_profiles') or ['business']
    if selected not in PROFILES or selected not in allowed:
        frappe.throw('此能力组合尚未授权')
    return dict(PROFILES[selected])


def selections(doc):
    value = preferences(doc).get('extension_selection') or {}
    if not isinstance(value, dict) or set(value) - {'skills', 'mcp'}:
        frappe.throw('扩展选择无效')
    for values in value.values():
        if (not isinstance(values, list) or len(values) > 16
                or any(not isinstance(item, str) or not 0 < len(item) <= 128 for item in values)
                or len(set(values)) != len(values)):
            frappe.throw('扩展选择超限或无效')
    return value


def enabled(doc, base, capability):
    config = settings(doc, base)
    return release(doc) == FULL and (config.get('capabilities') or {}).get(capability) is True
