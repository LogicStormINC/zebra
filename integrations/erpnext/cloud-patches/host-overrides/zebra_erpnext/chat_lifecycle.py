"""Conversation preferences, creation and metadata under admission."""

import json
from uuid import uuid4

import frappe
from frappe.utils import now_datetime

from zebra_erpnext import cloud


def run_options(model_profile=None, reasoning_effort=None):
    from zebra_erpnext import chat

    model = (
        model_profile
        if model_profile is not None
        else cloud.config().get("model_profile", chat.MODEL_OPTIONS[0]["value"])
    )
    effort = reasoning_effort if reasoning_effort is not None else "high"
    if model not in [item["value"] for item in chat.MODEL_OPTIONS] or effort not in [
        item["value"] for item in chat.REASONING_OPTIONS
    ]:
        frappe.throw("模型或思考强度配置无效")
    return {"model_profile": model, "reasoning_effort": effort}


def saved_options(doc):
    # Legacy conversations inherit their last submitted choices; preferences are
    # separate from immutable request_options used for unknown-result retries.
    from zebra_erpnext import chat

    value = json.loads(doc.preferences_json or doc.request_options or "{}")
    return chat.run_options(value.get("model_profile"), value.get("reasoning_effort"))


def settings(name):
    from zebra_erpnext import chat

    doc = cloud.owned(name)
    return {**chat.saved_options(doc), "company": doc.company}


def save_settings(name, model_profile, reasoning_effort):
    from redis.exceptions import LockError

    from zebra_erpnext import chat

    cloud.owned(name)
    options = chat.run_options(model_profile, reasoning_effort)
    try:
        with frappe.cache.lock(
            "zebra:submit:" + name, timeout=180, blocking_timeout=0
        ) as admission_lock:
            cloud.owned(name, for_update=True, admission_lock=admission_lock)
            frappe.db.set_value(
                "Zebra Conversation",
                name,
                "preferences_json",
                json.dumps(options),
                update_modified=False,
            )
            frappe.db.commit()  # publish preferences before releasing submit admission
            return options
    except LockError:
        frappe.throw("会话正在提交，请稍后保存配置")


def conversations():
    return frappe.get_all(
        "Zebra Conversation",
        filters={"user": cloud.principal(), "status": ["!=", "deleted"]},
        fields=[
            "name",
            "title",
            "company",
            "task_id",
            "active_run_id",
            "status",
            "modified",
            "creation",
        ],
        order_by="modified desc",
        limit_page_length=50,
    )


def create(title=None, company=None):
    from zebra_erpnext import chat

    user = cloud.principal()
    company = company or frappe.defaults.get_global_default("company")
    if not company:
        frappe.throw("请先选择公司")
    frappe.get_doc("Company", company).check_permission("read")
    doc = frappe.get_doc(
        dict(
            doctype="Zebra Conversation",
            user=user,
            title=str(title or "新会话")[:120],
            company=company,
            host_thread=str(uuid4()),
            workspace_ref=cloud.private_workspace_ref(user, company),
            preferences_json=json.dumps(chat.run_options()),
            status="idle",
        )
    )
    doc.db_insert()
    return doc.as_dict()


def manage(name, title=None, delete=False):
    """Reuse submit admission; metadata changes cannot race grant commits."""
    from redis.exceptions import LockError

    cloud.owned(name)
    if not delete and (not isinstance(title, str) or not title.strip() or len(title.strip()) > 120):
        frappe.throw("会话名称须为 1 到 120 个字符")
    try:
        with frappe.cache.lock(
            "zebra:submit:" + name, timeout=180, blocking_timeout=0
        ) as admission_lock:
            doc = cloud.owned(name, for_update=True, admission_lock=admission_lock)
            values = {"modified": now_datetime()}
            if delete:
                if doc.pending_command or doc.status == "dispatching":
                    frappe.throw("会话正在提交，请先重新连接并停止任务")
                if doc.task_id:
                    coordinates = (doc.task_id, doc.active_run_id)
                    header = cloud.request(
                        doc,
                        "GET",
                        f"/tasks/{doc.task_id}/header",
                        run_id=doc.active_run_id,
                        admission_lock=admission_lock,
                    )
                    # Grant issuance commits; re-read current ownership/state after
                    # that boundary while submit admission is still held.
                    doc = cloud.owned(name, for_update=True, admission_lock=admission_lock)
                    if (
                        (doc.task_id, doc.active_run_id) != coordinates
                        or doc.pending_command
                        or doc.status == "dispatching"
                    ):
                        frappe.throw("会话已变化，请重新连接并核对任务")
                    status = header.get("current_turn_status") or header.get("status")
                    if status not in {
                        "completed",
                        "failed",
                        "cancelled",
                        "stopped",
                        "suspended",
                        "waiting_input",
                        "awaiting_turn",
                        "awaiting_input",
                        "awaiting_approval",
                        "blocked",
                        "partial",
                    }:
                        frappe.throw("执行中的会话不能删除，请先停止任务")
                # ponytail: retain Cloud audit/history; deletion hides the Host mapping
                # and revokes pending approvals/grants instead of deleting business data.
                frappe.db.set_value(
                    "Zebra Business Approval",
                    {"conversation": name, "status": "Pending"},
                    "expires_at",
                    now_datetime(),
                )
                frappe.db.delete("Zebra Grant", {"conversation": name})
                values.update(status="deleted", client_surface_json=None)
            else:
                values["title"] = title.strip()
            frappe.db.set_value("Zebra Conversation", name, values, update_modified=False)
            frappe.db.commit()  # publish only managed fields before releasing admission
            return {"name": name, "title": values.get("title", doc.title), "deleted": bool(delete)}
    except LockError:
        frappe.throw("会话正在提交，请稍后重试")
