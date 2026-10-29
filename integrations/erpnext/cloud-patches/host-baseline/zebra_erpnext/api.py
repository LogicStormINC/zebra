"""Same-origin RPCs: Cloud credentials and arbitrary Cloud paths never leave the Host."""
import json
import frappe
from werkzeug.wrappers import Response
from zebra_erpnext import chat, cloud


@frappe.whitelist(methods=["GET", "POST"])
def bootstrap():
    user = cloud.principal()
    companies = frappe.get_list("Company", fields=["name"], limit_page_length=100)
    settings = frappe.conf.get("zebra_agent") or {}
    return dict(user=user, companies=[row.name for row in companies],
                company=frappe.defaults.get_global_default("company"),
                enabled=bool(settings.get("enabled")),
                model_profile=settings.get("model_profile", "deepseek-v4-flash-executor-v1"),
                model_options=chat.MODEL_OPTIONS, reasoning_options=chat.REASONING_OPTIONS, reasoning_effort="high",
                https_url="https://192.168.110.42:18443/desk")


@frappe.whitelist(methods=["GET", "POST"])
def conversations():
    return chat.conversations()


@frappe.whitelist(methods=["POST"])
def create_conversation(title=None, company=None):
    return chat.create(title, company)


@frappe.whitelist(methods=["POST"])
def submit(conversation, message, request_id, context=None, model_profile=None, reasoning_effort=None, attachments=None):
    return chat.submit(conversation, message, request_id, context, model_profile, reasoning_effort, attachments)


@frappe.whitelist(methods=["POST"])
def cancel(conversation):
    return chat.cancel(conversation)


@frappe.whitelist(methods=["GET", "POST"])
def approvals(conversation=None):
    user = cloud.principal()
    filters = {"user": user, "status": "Pending", "expires_at": [">", frappe.utils.now_datetime()]}
    if conversation:
        selected = cloud.owned(conversation)
        filters["company"] = selected.company
        filters["conversation"] = selected.name
    rows = frappe.get_all("Zebra Business Approval", filters=filters,
                         fields=["name", "operation", "arguments_json", "company", "expires_at"],
                         limit_page_length=20, order_by="creation desc")
    return [dict(row) for row in rows if frappe.has_permission("Company", "read", row.company)]


@frappe.whitelist(methods=["GET", "POST"])
def snapshot(conversation):
    doc = cloud.owned(conversation)
    rejected_request_id = doc.request_id if doc.status == 'rejected' and not doc.pending_command else None
    if not doc.task_id:
        return dict(messages=[], status="idle", run_id=None, run_state={"phase": "idle", "availableActions": []}, clarification=None, rejected_request_id=rejected_request_id)
    # The existing Task stream is an authorized, public event projection, not SQL access.
    from zebra_erpnext.history import load, messages, public_state
    from zebra_erpnext.presentation import decorate
    header, events = load(doc)
    surface = json.loads(doc.client_surface_json) if doc.client_surface_json else None
    if surface and "clientSessionId" not in surface:
        surface = None
    return dict(messages=decorate(cloud.owned(conversation), messages(events)),
                **public_state(header, events, pending_command=bool(doc.pending_command)),
                run_id=doc.active_run_id,
                accepted_request_id=doc.request_id if doc.status in {'running', 'cancelled'} and not doc.pending_command else None,
                rejected_request_id=rejected_request_id,
                client_surface=surface)


@frappe.whitelist(methods=["POST"])
def client_proxy(conversation, path, method, body=None, client_session=None, client_fence=None):
    from zebra_erpnext.client import proxy
    return proxy(conversation, path, method, body, client_session, client_fence)


@frappe.whitelist(methods=["GET"])
def events(conversation, cursor=None):
    doc = cloud.owned(conversation)
    if not doc.task_id or not doc.active_run_id:
        frappe.throw("会话尚无执行任务")
    if cursor and len(cursor) > 4096:
        frappe.throw("观察游标无效")
    response = cloud.request(doc, "GET",
        f"/agui/threads/{doc.task_id}/runs/{doc.active_run_id}/stream", run_id=doc.active_run_id,
        stream=True, params={"cursor": cursor} if cursor else None)

    def generate():
        try:
            for line in response.iter_lines(chunk_size=1):
                yield line + b"\n"
        except Exception:
            yield b'data: {"type":"OBSERVATION_ERROR","message":"Connection interrupted; reconnect without resubmitting."}\n\n'
        finally:
            response.close()
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@frappe.whitelist(methods=["POST"])
def rename_conversation(conversation, title):
    return chat.manage(conversation, title=title)


@frappe.whitelist(methods=["POST"])
def delete_conversation(conversation):
    return chat.manage(conversation, delete=True)


@frappe.whitelist(methods=["GET", "POST"])
def conversation_settings(conversation):
    return chat.settings(conversation)


@frappe.whitelist(methods=["POST"])
def save_conversation_settings(conversation, model_profile, reasoning_effort):
    return chat.save_settings(conversation, model_profile, reasoning_effort)


@frappe.whitelist(methods=["GET", "POST"])
def capability_catalog(conversation=None):
    from zebra_erpnext.features import catalog
    return catalog(conversation)


@frappe.whitelist(methods=["GET", "POST"])
def task_usage(conversation):
    from zebra_erpnext.resources import usage
    return usage(conversation)


@frappe.whitelist(methods=["GET", "POST"])
def task_artifacts(conversation):
    from zebra_erpnext.resources import artifacts
    return artifacts(conversation)


@frappe.whitelist(methods=["GET", "POST"])
def artifact_detail(conversation, artifact_id):
    from zebra_erpnext.resources import artifact_detail as detail
    return detail(conversation, artifact_id)


@frappe.whitelist(methods=["GET", "POST"])
def artifact_content(conversation, artifact_id):
    from zebra_erpnext.resources import artifact_content as content
    return content(conversation, artifact_id)


@frappe.whitelist(methods=["GET", "POST"])
def task_attachments(conversation, cursor=None):
    from zebra_erpnext.resources import attachments
    return attachments(conversation, cursor)


@frappe.whitelist(methods=["GET"])
def artifact_download(conversation, artifact_id):
    import base64
    from urllib.parse import quote
    from zebra_erpnext.resources import artifact_download as download
    value = download(conversation, artifact_id)
    payload = base64.b64decode(value["content_base64"], validate=True)
    return Response(payload, content_type="application/octet-stream", headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(value["file_name"], safe=""),
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@frappe.whitelist(methods=["GET"])
def artifact_preview(conversation, artifact_id):
    import base64
    from zebra_erpnext.resources import artifact_content, preview_mime
    value = artifact_content(conversation, artifact_id)
    mime = preview_mime(value['file_name'], value['media_type'])
    if not mime:
        frappe.throw('此类型不支持安全预览，请下载查看')
    return Response(base64.b64decode(value['content_base64'], validate=True), content_type=mime, headers={
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "sandbox; default-src 'none'; style-src 'unsafe-inline'"})


@frappe.whitelist(methods=["POST"])
def save_report(conversation, message_id, digest):
    from zebra_erpnext.presentation import save
    return save(conversation, message_id, digest, report=True)


@frappe.whitelist(methods=["POST"])
def answer_feedback(conversation, message_id, digest, feedback):
    from zebra_erpnext.presentation import save
    return save(conversation, message_id, digest, feedback)


@frappe.whitelist(methods=["GET"])
def report_download(conversation, message_id, digest):
    from zebra_erpnext.presentation import download
    return Response(download(conversation, message_id, digest), content_type='application/octet-stream', headers={
        'Content-Disposition': 'attachment; filename="zebra-report.md"',
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})
