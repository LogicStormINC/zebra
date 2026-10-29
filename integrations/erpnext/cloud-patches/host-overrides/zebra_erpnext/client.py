"""Published browser capabilities, with Host-owned conversation/run fencing."""
import hmac
import json
import re
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import frappe
from zebra_erpnext import cloud


def open_surface(doc, run_id, page, admission_lock):
    doc = cloud.owned(doc.name, for_update=True, admission_lock=admission_lock)
    settings = cloud.config()
    cloud.require_admission_open(settings)
    profile = settings.get("frontend_profile")
    if not profile or frappe.local.request.headers.get("Origin") != settings["origin"]:
        return None
    previous = json.loads(doc.client_surface_json or "{}")
    if previous.get("runId") == run_id:
        return previous
    if previous.get("opening_run"):
        if time.time() - previous["opening_at"] < 420:
            frappe.throw("页面连接结果尚未确定，请在七分钟后重连；不会重复开启页面控制会话")
        previous = {}
    if previous:
        cloud.request(doc, "POST", f"/v1/client-sessions/{previous['clientSessionId']}/release",
            run_id=previous["runId"], body=dict(task_id=previous["taskId"], run_id=previous["runId"],
                run_binding_id=previous["runBindingId"]),
            extra_headers={"X-Zebra-Client-Session": previous["sessionCredential"],
                           "X-Zebra-Client-Fence": previous["controllerFenceToken"]},
            accepted_problems=((409, "stale_client_fence"), (410, "client_session_expired"),
                               (401, "client_session_authorization_required")), admission_lock=admission_lock)
        doc = cloud.owned(doc.name, for_update=True, admission_lock=admission_lock)
        doc.client_surface_json = None
        doc.db_update()
        frappe.db.commit()
    actions = profile["actions"]
    now = datetime.now(UTC)
    body = dict(grant=dict(grant_id=str(uuid4()), host_app_id="erpnext", namespace_id="erpnext",
                          frontend_app_id="erpnext-web", origin=settings["origin"], user_ref=doc.user,
                          profile_digest=profile["digest"], scopes=["client.action", "client.read"],
                          expires_at=(now + timedelta(minutes=25)).isoformat()),
                mount=dict(frontend_app_id="erpnext-web", profile_revision=profile["revision"],
                           profile_digest=profile["digest"], mounted_readables=["erpnext.ui.context"],
                           mounted_actions=[item["name"] for item in actions], ui_revision=1,
                           mounted_at=now.isoformat()),
                task_capability_scope=[item["name"] for item in actions], controller=True)
    # The native API intentionally does not replay credential-bearing responses.
    # Persist admission before the call; unknown results wait out its 5m lease
    # plus transport margin, rather than opening another active controller.
    doc = cloud.owned(doc.name, for_update=True, admission_lock=admission_lock)
    doc.client_surface_json = json.dumps(dict(opening_run=run_id, opening_at=time.time()))
    doc.db_update()
    frappe.db.commit()
    opened = cloud.request(doc, "POST", f"/v1/tasks/{doc.task_id}/runs/{run_id}/client-surface",
                           body=body, run_id=run_id, admission_lock=admission_lock)
    surface = dict(baseUrl="", clientSessionId=opened["client_session_id"],
                   sessionCredential=opened["session_credential"],
                   controllerFenceToken=opened["controller_fence_token"],
                   taskId=doc.task_id, runId=run_id, runBindingId=opened["binding_id"],
                   clientBindingDigest=opened["binding_digest"],
                   actionContractDigests=profile["action_digests"], initialUiRevision=1)
    doc = cloud.owned(doc.name, for_update=True, admission_lock=admission_lock)
    doc.client_surface_json = json.dumps(surface)
    doc.db_update()
    frappe.db.commit()
    return surface


def proxy(conversation, path, method, body, client_session, client_fence):
    doc = cloud.owned(conversation)
    surface = json.loads(doc.client_surface_json or "{}")
    if (not surface or surface.get("runId") != doc.active_run_id
            or not hmac.compare_digest(str(client_session), surface["sessionCredential"])
            or not hmac.compare_digest(str(client_fence), surface["controllerFenceToken"])):
        frappe.throw("客户端会话不属于当前用户或执行轮次", frappe.PermissionError)
    session = surface["clientSessionId"]
    allowed = {
        ("GET", f"/v1/client-sessions/{session}/effects"),
        ("POST", f"/v1/client-sessions/{session}/heartbeat"),
        ("POST", f"/v1/client-sessions/{session}/release"),
    }
    method = str(method).upper()
    receipt = method == "POST" and re.fullmatch(r"/v1/client-effects/[0-9a-f-]{36}/receipts", path)
    if (method, path) not in allowed and not receipt:
        frappe.throw("客户端代理路由未开放", frappe.PermissionError)
    if body == "":  # Frappe form encoding sends a missing GET body as an empty string.
        body = None
    payload = frappe.parse_json(body) if isinstance(body, str) and body else body
    if payload is not None and not isinstance(payload, dict):
        frappe.throw("客户端请求格式无效")
    if len(json.dumps(payload)) > 100000:
        frappe.throw("客户端请求过大")
    headers = {"X-Zebra-Client-Session": surface["sessionCredential"],
               "X-Zebra-Client-Fence": surface["controllerFenceToken"]}
    if receipt and not receipt_ready(doc, path, headers):
        return dict(status=503, body={"status": "preparing", "reason": "worker_not_parked"})
    response = cloud.request(doc, method, path, body=payload, run_id=doc.active_run_id,
                          raw_response=True, key="sdk-receipt:" + path.split("/")[3] if receipt else None,
                          extra_headers=headers)
    try:
        return dict(status=response.status_code, body=response.json())
    finally:
        response.close()


def receipt_ready(doc, path, headers):
    # Fast local actions can finish before this deployed Worker commits its
    # waiting event. Gate first receipts on canonical state to avoid a journal
    # sequence race; already-recorded receipts can always replay idempotently.
    effect = cloud.request(doc, "GET", path.removesuffix("/receipts"),
                           run_id=doc.active_run_id, extra_headers=headers)
    if effect.get("status") not in {"pending", "delivered"}:
        return True
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        header = cloud.request(doc, "GET", f"/tasks/{doc.task_id}/header", run_id=doc.active_run_id)
        if header.get("status") in {"waiting_client_effect", "failed", "cancelled", "completed", "suspended"}:
            return True
        time.sleep(0.1)
    return False
