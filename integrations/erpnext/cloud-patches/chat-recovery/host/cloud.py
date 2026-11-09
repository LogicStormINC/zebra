"""Small Host adapter: native OpenSSL signing, fresh grants, existing Cloud wire."""

import base64
import hashlib
import json
import subprocess
import time
from datetime import timedelta
from uuid import uuid4

import frappe
import requests
from frappe.utils import now_datetime

SCOPES = ["agent.run", "erpnext.read", "artifact.read"]


class CloudRejectedError(frappe.ValidationError):
    def __init__(self, status, reason):
        self.status_code, self.reason = status, reason
        super().__init__(f"Zebra Cloud 拒绝请求（{status}: {reason}）")


def config():
    value = frappe.conf.get("zebra_agent") or {}
    if not value.get("enabled"):
        frappe.throw("Zebra Agent 尚未启用")
    for key in ("base_url", "issuer", "origin", "signing_key", "ca_file", "host_secret"):
        if not value.get(key):
            frappe.throw("Zebra Agent 服务端配置不完整")
    return value


def require_admission_open(settings=None):
    if (settings if settings is not None else config()).get("admission_paused") is True:
        frappe.throw("Agent 正在维护，暂时暂停新提交；历史记录仍可查看")


def require_chat_generation(conversation):
    if (
        config().get("chat_readonly_enabled") is True
        and conversation.task_id
        and json.loads(conversation.request_options or "{}").get("chat_readonly_generation")
        is not True
    ):
        frappe.throw("此历史会话保留为只读，请新建会话继续文字查询。")


def principal():
    user = frappe.session.user
    if user == "Guest" or not frappe.db.get_value("User", user, "enabled"):
        frappe.throw("请先登录 ERPNext", frappe.PermissionError)
    return user


def owned(name, *, for_update=False):
    user = principal()
    doc = frappe.get_doc("Zebra Conversation", name, for_update=for_update)
    if doc.user != user or doc.status == "deleted":
        frappe.throw("会话不存在", frappe.PermissionError)
    frappe.get_doc("Company", doc.company).check_permission("read")
    return doc


def _b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def private_workspace_ref(user, company):
    """Private file scope, stable per site + ERP principal + company."""
    return (
        "erp-u-"
        + hashlib.sha256((frappe.local.site + "\0" + user + "\0" + company).encode()).hexdigest()[
            :40
        ]
    )


def has_private_workspace(conversation):
    return conversation.workspace_ref == private_workspace_ref(
        conversation.user, conversation.company
    )


def grant(conversation, run_id=None):
    settings = config()
    principal()
    if conversation.user != frappe.session.user:
        frappe.throw("会话归属不匹配", frappe.PermissionError)
    frappe.get_doc("Company", conversation.company).check_permission("read")
    now = int(time.time())
    if not conversation.workspace_ref:
        if conversation.task_id:
            frappe.throw("旧任务缺少已绑定的工作区，请先核对映射")
        conversation.workspace_ref = private_workspace_ref(conversation.user, conversation.company)
        conversation.db_update()
    grant_id = str(uuid4())
    resources = [
        {"type": "thread", "id": conversation.host_thread},
        {"type": "principal", "id": conversation.user},
    ]
    readonly_chat = settings.get("chat_readonly_enabled") is True
    if readonly_chat:
        resources.append({"type": "company", "id": conversation.company})
    if run_id:
        resources.append({"type": "run", "id": run_id})
    claims = dict(
        iss=settings["issuer"],
        aud="zebra",
        sub=conversation.user,
        jti=grant_id,
        iat=now,
        nbf=now,
        exp=now + 1800,
        host_app_id="erpnext",
        namespace_id="erpnext",
        workspace_ref=conversation.workspace_ref,
        resource_refs=resources,
        scopes=["agent.run", "erpnext.read"] if readonly_chat else SCOPES,
        origin=settings["origin"],
        policy_version="erpnext-v1",
        limits=dict(
            max_runtime_seconds=600,
            max_model_tokens=40000,
            max_artifact_bytes=1 if readonly_chat else 20 * 1024 * 1024,
        ),
    )
    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT", "kid": "erpnext-v1"}).encode())
    payload = _b64(json.dumps(claims, ensure_ascii=False, separators=(",", ":")).encode())
    signing = f"{header}.{payload}".encode()
    signed = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", settings["signing_key"]],
        input=signing,
        capture_output=True,
        check=True,
        timeout=10,
    )
    frappe.get_doc(
        dict(
            doctype="Zebra Grant",
            name=grant_id,
            user=conversation.user,
            company=conversation.company,
            conversation=conversation.name,
            run_id=run_id,
            workspace_ref=conversation.workspace_ref,
            expires_at=now_datetime() + timedelta(minutes=30),
        )
    ).db_insert()
    # A synchronous Worker callback must see the issued authority mapping.
    frappe.db.commit()
    return f"{header}.{payload}.{_b64(signed.stdout)}"


def request(
    conversation,
    method,
    path,
    *,
    body=None,
    run_id=None,
    key=None,
    stream=False,
    params=None,
    extra_headers=None,
    _attempt=0,
    accepted_problems=(),
    raw_response=False,
):
    settings = config()
    if method.upper() != "GET":
        require_admission_open(settings)
    headers = {
        "Authorization": "Bearer " + grant(conversation, run_id),
        "Accept": "text/event-stream" if stream else "application/json",
    }
    if key:
        headers["Idempotency-Key"] = key
    if extra_headers:
        headers.update(extra_headers)
    try:
        response = requests.request(
            method,
            settings["base_url"].rstrip("/") + path,
            headers=headers,
            json=body,
            params=params,
            verify=settings["ca_file"],
            timeout=(10, 65),
            stream=stream,
        )
    except requests.RequestException:
        frappe.throw("Zebra Cloud 连接失败；任务不会自动重复提交")
    if raw_response:
        return response
    if not response.ok:
        try:
            problem = response.json()
            reason = str(problem.get("code") or problem.get("reason") or problem.get("status"))[
                :240
            ]
        except ValueError:
            reason = "upstream_error"
        status = response.status_code
        response.close()
        if (status, reason) in accepted_problems:
            return problem
        if (
            method == "GET"
            and status == 409
            and reason in {"projection_not_ready", "canonical_task_incomplete"}
            and _attempt < 5
        ):
            time.sleep(0.25 * 2**_attempt)
            return request(
                conversation,
                method,
                path,
                body=body,
                run_id=run_id,
                key=key,
                stream=stream,
                params=params,
                extra_headers=extra_headers,
                _attempt=_attempt + 1,
                accepted_problems=accepted_problems,
            )
        frappe.throw(
            f"Zebra Cloud 拒绝请求（{status}: {reason}）", CloudRejectedError(status, reason)
        )
    if stream:
        return response
    try:
        return response.json()
    finally:
        response.close()
