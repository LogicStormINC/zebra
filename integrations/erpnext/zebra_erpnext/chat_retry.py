"""Durable fresh-validation retries with exact request receipts."""

import json
from uuid import UUID, uuid4

import frappe
from frappe.utils import now_datetime

from zebra_erpnext import cloud


def retry_fresh(name, run_id, accepted_event_id, operation_id):
    """Explicit empty-message RUN; preserve one durable intent across lost ACKs."""
    from redis.exceptions import LockError

    from zebra_erpnext import chat

    cloud.owned(name)
    cloud.require_admission_open()
    try:
        run_id, accepted_event_id, operation_id = (
            str(UUID(value)) for value in (run_id, accepted_event_id, operation_id)
        )
    except (ValueError, TypeError, AttributeError):
        frappe.throw("重新验证操作的标识无效")
    try:
        with frappe.cache.lock(
            "zebra:submit:" + name, timeout=180, blocking_timeout=0
        ) as admission_lock:
            return chat._retry_fresh(name, run_id, accepted_event_id, operation_id, admission_lock)
    except LockError:
        frappe.throw("会话正在提交，请稍后用同一操作重试")


def _retry_fresh(name, run_id, accepted_event_id, operation_id, admission_lock):
    from zebra_erpnext import chat

    doc = cloud.owned(name, for_update=True, admission_lock=admission_lock)
    options = json.loads(doc.request_options or "{}")
    operation = options.get("fresh_retry") or {}
    if operation.get("operation_id") == operation_id:
        if (operation.get("predecessor_run_id"), operation.get("predecessor_event_id")) != (
            run_id,
            accepted_event_id,
        ):
            frappe.throw("同一操作不能用于不同的原请求")
        if operation.get("phase") in {"accepted", "rejected"}:
            return {
                "status": operation["phase"],
                "task_id": doc.task_id,
                "run_id": operation["run_id"] if operation["phase"] == "accepted" else run_id,
            }
    else:
        if operation.get("phase") in {"preparing", "dispatching"} or doc.pending_command:
            frappe.throw("已有提交结果尚未确定，请重新连接原操作")
        if not doc.task_id or doc.active_run_id != run_id or doc.stop_command:
            frappe.throw("原请求已变化，请刷新会话")
        operation = dict(
            operation_id=operation_id,
            predecessor_run_id=run_id,
            predecessor_event_id=accepted_event_id,
            run_id=str(uuid4()),
            phase="preparing",
            predecessor_status=doc.status,
        )
        options["fresh_retry"] = operation
        doc.request_options = json.dumps(options)
        doc.db_update()
        frappe.db.commit()  # Durable intent BEFORE grant issuance or client-surface mutations.

    def current(expected_phase):
        owned = cloud.owned(name, for_update=True, admission_lock=admission_lock)
        saved = json.loads(owned.request_options or "{}").get("fresh_retry", {})
        expected_run = operation["run_id"] if expected_phase == "dispatching" else run_id
        if (
            saved != operation
            or saved.get("phase") != expected_phase
            or owned.active_run_id != expected_run
        ):
            frappe.throw("会话坐标已变化，请重新连接核对")
        return owned

    def reject_known():
        nonlocal doc
        doc = current(operation["phase"])
        operation["phase"] = "rejected"
        options["fresh_retry"] = operation
        doc.request_options = json.dumps(options)
        doc.active_run_id = run_id
        doc.status = operation["predecessor_status"]
        doc.pending_command = None
        doc.db_update()
        frappe.db.commit()

    def eligible():
        header = cloud.request(
            doc, "GET", f"/tasks/{doc.task_id}/header", run_id=run_id, admission_lock=admission_lock
        )
        outcome = header.get("command_outcome") or {}
        if (
            outcome.get("run_id"),
            outcome.get("accepted_event_id"),
            outcome.get("retry_eligible"),
        ) != (run_id, accepted_event_id, True):
            reject_known()
            frappe.throw("原请求已不满足安全继续条件，请刷新或停止任务")
        return header

    posting_command = False
    first_post = False
    try:
        if operation["phase"] == "preparing":
            doc = current("preparing")
            eligible()
            doc = current("preparing")
            from zebra_erpnext.client import open_surface

            surface = open_surface(
                doc, operation["run_id"], options.get("context", {}), admission_lock
            )
            # Native opening_run/opening_at is deliberately preserved on unknown
            # response. No operation retry clears its seven-minute ownership fence.
            doc = current("preparing")
            header = eligible()
            doc = current("preparing")
            revision = header.get("active_segment_sequence", header.get("current_sequence"))
            if type(revision) is not int or revision < 0:
                frappe.throw("任务版本不可用，请重新连接")
            body = chat._run_body(
                doc, operation["run_id"], revision, options.get("context", {}), surface, []
            )
            doc.pending_command = json.dumps(body, ensure_ascii=False)
            operation["phase"] = "dispatching"
            options["fresh_retry"] = operation
            doc.request_options = json.dumps(options)
            doc.active_run_id = operation["run_id"]
            doc.status = "dispatching"
            doc.stop_command = None
            doc.db_update()
            frappe.db.commit()  # Immutable exact body/revision/Run/key before AG-UI POST.
            # Only this invocation knows no earlier POST existed. A resumed
            # durable dispatching phase is unknown even if a crash preceded POST.
            first_post = True
        doc = current("dispatching")
        body = json.loads(doc.pending_command)
        if (
            body.get("runId") != operation["run_id"]
            or body.get("threadId") != doc.task_id
            or body.get("action") != "run"
            or body.get("input", {}).get("messages") != []
        ):
            frappe.throw("已保存的继续请求不一致，请核对任务")
        posting_command = True
        fresh_headers = {}
        if isinstance(body.get("input", {}).get("forwardedProps"), dict) and body["input"][
            "forwardedProps"
        ].get("clientSessionId"):
            fresh_surface = json.loads(doc.client_surface_json or "{}")
            if fresh_surface.get("sessionCredential"):
                fresh_headers["X-Zebra-Client-Session"] = fresh_surface["sessionCredential"]
        cloud.request(
            doc,
            "POST",
            "/agui/commands",
            body=body,
            run_id=operation["run_id"],
            key=f"erpnext-fresh-{operation_id}",
            admission_lock=admission_lock,
            extra_headers=fresh_headers or None,
        )
    except cloud.CloudRejectedError as error:
        # Only the first send's exact pre-acceptance problem can discharge this
        # operation. Renewal/validation can reject a later resend before native
        # idempotency, which says nothing about an earlier accepted, lost ACK.
        known = {
            (400, "invalid_request"),
            (400, "missing_idempotency_key"),
            (403, "host_binding_renewal_rejected"),
            (403, "extension_authority_required"),
            (403, "extension_authority_rejected"),
            (409, "revision_conflict"),
            (409, "host_binding_revision_conflict"),
            (409, "host_binding_missing"),
            (422, "client_admission_rejected"),
        }
        if first_post and posting_command and (error.status_code, error.reason) in known:
            reject_known()
        raise
    doc = current("dispatching")
    operation["phase"] = "accepted"
    options["fresh_retry"] = operation
    doc.request_options = json.dumps(options)
    doc.pending_command = None
    doc.status = "running"
    doc.modified = now_datetime()
    doc.db_update()
    frappe.db.commit()
    return {
        "status": "accepted",
        "task_id": doc.task_id,
        "run_id": operation["run_id"],
        "client_surface": json.loads(doc.client_surface_json or "null"),
    }
