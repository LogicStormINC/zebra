"""Owner-scoped Native schedules; no local cron, implicit approval or business replay."""

import hashlib
import json
from uuid import UUID

import frappe

from zebra_erpnext import chat, cloud, runtime


def require(conversation):
    doc = cloud.owned(conversation)
    if not runtime.enabled(doc, cloud.config(), "schedules"):
        frappe.throw("此会话尚未开放原生定时任务")
    return doc


def owned(doc, name):
    record = frappe.get_doc("Zebra Schedule", name)
    if (
        record.user != doc.user
        or record.company != doc.company
        or record.runtime_ref != runtime.release(doc)
        or record.status == "deleted"
    ):
        frappe.throw("定时任务不存在", frappe.PermissionError)
    return record


def inventory(conversation):
    doc = require(conversation)
    records = frappe.get_all(
        "Zebra Schedule",
        filters={
            "user": doc.user,
            "company": doc.company,
            "runtime_ref": runtime.release(doc),
            "status": ["!=", "deleted"],
        },
        fields=["name", "native_id", "title", "status", "modified"],
        order_by="modified desc",
        limit_page_length=100,
    )
    return {"schedules": records}


def create(conversation, title, prompt, trigger, request_id, timezone="Asia/Shanghai"):
    from redis.exceptions import LockError

    doc = require(conversation)
    try:
        key = str(UUID(request_id))
    except (ValueError, TypeError, AttributeError):
        frappe.throw("计划请求标识必须是 UUID")
    if (
        not isinstance(title, str)
        or not 0 < len(title.strip()) <= 120
        or not isinstance(prompt, str)
        or not 0 < len(prompt.strip()) <= 30000
    ):
        frappe.throw("请填写计划名称与执行内容")
    trigger = frappe.parse_json(trigger) if isinstance(trigger, str) else trigger
    if not isinstance(trigger, dict) or trigger.get("kind") not in {
        "once",
        "interval",
        "daily",
        "weekly",
    }:
        frappe.throw("计划时间无效")
    options = chat.saved_options(doc)
    from zebra_erpnext.extensions import task_skills

    body = {
        "title": title.strip(),
        "timezone": timezone,
        "trigger": trigger,
        "task_template": {
            "prompt": prompt.strip(),
            "title": title.strip(),
            "interaction_mode": "conversation",
            **options,
            **runtime.profile(doc, cloud.config()),
            "workspace_source": {"kind": "host_reference", "locator": "erpnext://schedule/" + key},
            "skill_components": task_skills(doc),
            "extension_selection": runtime.selections(doc),
            "stream_capabilities": {
                "wire_version": 2,
                "provisional_draft_label": True,
                "replace_message": True,
                "reset_provisional": True,
                "scoped_resume": True,
            },
            "max_model_calls": 20,
            "max_tool_calls": 48,
        },
    }
    request_key = hashlib.sha256(
        (frappe.local.site + "\0" + doc.user + "\0" + doc.company + "\0" + key).encode()
    ).hexdigest()
    try:
        with frappe.cache.lock(
            "zebra:schedule-create:" + request_key, timeout=180, blocking_timeout=0
        ):
            name = frappe.db.get_value("Zebra Schedule", {"request_key": request_key}, "name")
            if name:
                record = owned(doc, name)
                if json.loads(record.body_json) != body:
                    frappe.throw("同一请求标识不能更改计划内容")
            else:
                record = frappe.get_doc(
                    {
                        "doctype": "Zebra Schedule",
                        "title": title.strip(),
                        "user": doc.user,
                        "company": doc.company,
                        "conversation": doc.name,
                        "request_key": request_key,
                        "runtime_ref": runtime.release(doc),
                        "status": "creating",
                        "body_json": json.dumps(body),
                        "preferences_json": doc.preferences_json,
                    }
                )
                record.db_insert()
                frappe.db.commit()
            result = cloud.request(
                doc,
                "POST",
                "/schedules",
                body=body,
                key="erp-schedule-" + request_key,
                authority_refs=[{"type": "schedule_request", "id": record.name}],
            )
            current = frappe.get_doc("Zebra Schedule", record.name, for_update=True)
            identity = str(UUID(result["schedule_id"]))
            if current.native_id and current.native_id != identity:
                frappe.throw("计划回执归属冲突；不会再次创建")
            frappe.db.set_value(
                "Zebra Schedule",
                record.name,
                {
                    "native_id": identity,
                    **({"status": "active"} if current.status == "creating" else {}),
                },
            )
            frappe.db.commit()
            return {"name": record.name, **result}
    except LockError:
        frappe.throw("计划正在创建，请使用原请求核对")


def detail(conversation, name):
    doc = require(conversation)
    record = owned(doc, name)
    if not record.native_id:
        return {"name": record.name, "status": record.status, "pending": True}
    value = cloud.request(doc, "GET", "/schedules/" + str(UUID(record.native_id)))
    expected = {"pausing": {"paused", "deleted"}, "resuming": {"active"}}.get(record.status, set())
    if value.get("status") in expected:
        frappe.db.set_value("Zebra Schedule", record.name, "status", value["status"])
    return {"name": record.name, "host_status": record.status, **value}


def action(conversation, name, operation, schedule_version):
    doc = require(conversation)
    record = owned(doc, name)
    if operation not in {"pause", "resume", "delete"}:
        frappe.throw("计划操作无效")
    if type(schedule_version) is not int or schedule_version < 1:
        frappe.throw("计划版本无效，请先刷新")
    from redis.exceptions import LockError

    try:
        with frappe.cache.lock(
            "zebra:schedule-action:" + record.name, timeout=180, blocking_timeout=0
        ):
            if not record.native_id:
                frappe.throw("创建结果尚未确认，请使用原请求核对")
            # Pending pause/revocation blocks the next fresh Host execution gate
            # even when the Native HTTP acknowledgement is lost.
            frappe.db.set_value(
                "Zebra Schedule",
                record.name,
                "status",
                "pausing" if operation != "resume" else "resuming",
            )
            frappe.db.commit()
            path = "/schedules/" + str(UUID(record.native_id))
            result = cloud.request(
                doc,
                "DELETE" if operation == "delete" else "POST",
                path + ("/" + operation if operation != "delete" else ""),
                extra_headers={"If-Match": f'"{schedule_version!s}"'},
            )
            frappe.db.set_value(
                "Zebra Schedule",
                record.name,
                "status",
                result.get("status", "deleted" if operation == "delete" else "paused"),
            )
            frappe.db.commit()
            return result
    except LockError:
        frappe.throw("计划正在更新，请先刷新核对")
