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
    return dict(
        user=user,
        companies=[row.name for row in companies],
        company=frappe.defaults.get_global_default("company"),
        enabled=bool(settings.get("enabled")),
        admission_paused=settings.get("admission_paused") is True,
        model_profile=settings.get("model_profile", "deepseek-v4-flash-executor-v1"),
        model_options=chat.MODEL_OPTIONS,
        reasoning_options=chat.REASONING_OPTIONS,
        reasoning_effort="high",
        https_url="https://192.168.110.42:18443/desk",
    )


@frappe.whitelist(methods=["GET", "POST"])
def conversations():
    return chat.conversations()


@frappe.whitelist(methods=["POST"])
def create_conversation(title=None, company=None):
    return chat.create(title, company)


@frappe.whitelist(methods=["POST"])
def submit(
    conversation,
    message,
    request_id,
    context=None,
    model_profile=None,
    reasoning_effort=None,
    attachments=None,
):
    from zebra_erpnext import legacy_chat, runtime

    handler = legacy_chat if runtime.release(cloud.owned(conversation)) == runtime.LEGACY else chat
    return handler.submit(
        conversation, message, request_id, context, model_profile, reasoning_effort, attachments
    )


@frappe.whitelist(methods=["POST"])
def retry_fresh(conversation, run_id, accepted_event_id, operation_id):
    return chat.retry_fresh(conversation, run_id, accepted_event_id, operation_id)


@frappe.whitelist(methods=["POST"])
def cancel(conversation):
    from zebra_erpnext import legacy_chat, runtime

    handler = legacy_chat if runtime.release(cloud.owned(conversation)) == runtime.LEGACY else chat
    return handler.cancel(conversation)


@frappe.whitelist(methods=["GET", "POST"])
def approvals(conversation=None):
    user = cloud.principal()
    filters = {"user": user, "status": "Pending", "expires_at": [">", frappe.utils.now_datetime()]}
    if conversation:
        selected = cloud.owned(conversation)
        filters["company"] = selected.company
        filters["conversation"] = selected.name
    rows = frappe.get_all(
        "Zebra Business Approval",
        filters=filters,
        fields=["name", "operation", "arguments_json", "company", "expires_at"],
        limit_page_length=20,
        order_by="creation desc",
    )
    return [dict(row) for row in rows if frappe.has_permission("Company", "read", row.company)]


@frappe.whitelist(methods=["GET", "POST"])
def snapshot(conversation):
    doc = cloud.owned(conversation)
    rejected_request_id = (
        doc.request_id if doc.status == "rejected" and not doc.pending_command else None
    )
    if not doc.task_id:
        return dict(
            messages=[],
            status="idle",
            run_id=None,
            run_state={"phase": "idle", "availableActions": []},
            clarification=None,
            rejected_request_id=rejected_request_id,
        )
    # The existing Task stream is an authorized, public event projection, not SQL access.
    from zebra_erpnext.history import load, messages, public_state
    from zebra_erpnext.presentation import decorate

    header, events = load(doc)
    surface = json.loads(doc.client_surface_json) if doc.client_surface_json else None
    if surface and "clientSessionId" not in surface:
        surface = None
    state = public_state(header, events, pending_command=bool(doc.pending_command))
    retry = json.loads(doc.request_options or "{}").get("fresh_retry", {})
    if retry.get("phase") in {"preparing", "dispatching"}:
        state.update(
            status="blocked",
            canonical_status=header.get("status"),
            run_state={
                "phase": "terminal",
                "outcome": "blocked",
                "availableActions": ["retry"],
                "safeMessage": "上次重新验证的结果尚未确定，请继续原操作核对；不会追加消息",
            },
        )
    return dict(
        messages=decorate(cloud.owned(conversation), messages(events)),
        **state,
        run_id=doc.active_run_id,
        fresh_retry={
            key: value
            for key, value in json.loads(doc.request_options or "{}").get("fresh_retry", {}).items()
            if key in {"operation_id", "predecessor_run_id", "predecessor_event_id", "phase"}
        },
        accepted_request_id=doc.request_id
        if doc.status in {"running", "cancelled"} and not doc.pending_command
        else None,
        rejected_request_id=rejected_request_id,
        client_surface=surface,
    )


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
    response = cloud.request(
        doc,
        "GET",
        f"/agui/threads/{doc.task_id}/runs/{doc.active_run_id}/stream",
        run_id=doc.active_run_id,
        stream=True,
        params={"cursor": cursor} if cursor else None,
    )

    def generate():
        try:
            for line in response.iter_lines(chunk_size=1):
                yield line + b"\n"
        except Exception:
            yield (
                b'data: {"type":"OBSERVATION_ERROR","message":"Connection interrupted; '
                b'reconnect without resubmitting."}\n\n'
            )
        finally:
            response.close()

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
def task_artifacts(conversation, segment_id=None):
    from zebra_erpnext.resources import artifacts

    return artifacts(conversation, segment_id)


@frappe.whitelist(methods=["GET", "POST"])
def artifact_detail(conversation, artifact_id, segment_id=None):
    from zebra_erpnext.resources import artifact_detail as detail

    return detail(conversation, artifact_id, segment_id)


@frappe.whitelist(methods=["GET", "POST"])
def artifact_content(conversation, artifact_id, segment_id=None):
    from zebra_erpnext.resources import artifact_content as content

    return content(conversation, artifact_id, segment_id)


@frappe.whitelist(methods=["GET", "POST"])
def task_attachments(conversation, cursor=None):
    from zebra_erpnext.resources import attachments

    return attachments(conversation, cursor)


@frappe.whitelist(methods=["GET"])
def artifact_download(conversation, artifact_id, segment_id=None):
    import base64
    from urllib.parse import quote

    from zebra_erpnext.resources import artifact_download as download

    value = download(conversation, artifact_id, segment_id)
    payload = base64.b64decode(value["content_base64"], validate=True)
    return Response(
        payload,
        content_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(value["file_name"], safe=""),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@frappe.whitelist(methods=["GET"])
def artifact_preview(conversation, artifact_id, segment_id=None):
    import base64

    from zebra_erpnext.resources import artifact_content, preview_mime

    value = artifact_content(conversation, artifact_id, segment_id)
    mime = preview_mime(value["file_name"], value["media_type"])
    if not mime:
        frappe.throw("此类型不支持安全预览，请下载查看")
    return Response(
        base64.b64decode(value["content_base64"], validate=True),
        content_type=mime,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'",
        },
    )


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

    return Response(
        download(conversation, message_id, digest),
        content_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="zebra-report.md"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@frappe.whitelist(methods=["GET", "POST"])
def extension_inventory(conversation, kind="skills", cursor=None):
    from zebra_erpnext import extensions

    return extensions.inventory(conversation, kind, cursor)


@frappe.whitelist(methods=["POST"])
def configure_capabilities(conversation, capability_profile="business", selection=None):
    from zebra_erpnext import extensions

    return extensions.configure(conversation, capability_profile, selection)


@frappe.whitelist(methods=["POST"])
def extension_toggle(conversation, kind, item, expected_revision, enabled):
    from zebra_erpnext import extensions

    return extensions.toggle(conversation, kind, item, expected_revision, enabled)


@frappe.whitelist(methods=["POST"])
def extension_create(
    conversation, kind, request_id, endpoint=None, skill_id=None, version_id=None, auth_mode="none"
):
    from zebra_erpnext import extensions

    return extensions.create(
        conversation, kind, request_id, endpoint, skill_id, version_id, auth_mode
    )


@frappe.whitelist(methods=["POST"])
def extension_refresh(conversation, item, expected_revision):
    from zebra_erpnext import extensions

    return extensions.refresh(conversation, item, expected_revision)


@frappe.whitelist(methods=["GET", "POST"])
def knowledge_inventory(conversation):
    from zebra_erpnext import knowledge

    return knowledge.inventory(conversation)


@frappe.whitelist(methods=["POST"])
def knowledge_create(conversation, title, attachment):
    from zebra_erpnext import knowledge

    return knowledge.create(conversation, title, attachment)


@frappe.whitelist(methods=["POST"])
def knowledge_select(conversation, source_ids):
    from zebra_erpnext import knowledge

    return knowledge.select(conversation, source_ids)


@frappe.whitelist(methods=["POST"])
def knowledge_remove(conversation, name):
    from zebra_erpnext import knowledge

    return knowledge.remove(conversation, name)


@frappe.whitelist(methods=["POST"])
def memory_manage(conversation, action="list", text=None, memory_id=None, revision=None):
    from zebra_erpnext import knowledge

    return knowledge.memory(conversation, action, text, memory_id, revision)


@frappe.whitelist(methods=["GET", "POST"])
def artifact_segments(conversation, after=-1):
    from zebra_erpnext.resources import segments

    return segments(conversation, after)


@frappe.whitelist(methods=["POST"])
def extension_credentials(conversation, item, expected_revision, token=None):
    from zebra_erpnext import extensions

    return extensions.credentials(conversation, item, expected_revision, token)


@frappe.whitelist(methods=["POST"])
def skill_import(conversation, content_base64, request_id):
    from zebra_erpnext import extensions

    return extensions.import_skill(conversation, content_base64, request_id)


@frappe.whitelist(methods=["GET", "POST"])
def plugin_market(conversation, cursor=None):
    from zebra_erpnext import extensions

    return extensions.plugin_market(conversation, cursor)


@frappe.whitelist(methods=["GET", "POST"])
def plugin_inventory(conversation, cursor=None):
    from zebra_erpnext import extensions

    return extensions.plugin_inventory(conversation, cursor)


@frappe.whitelist(methods=["POST"])
def plugin_install(conversation, package_digest, request_id):
    from zebra_erpnext import extensions

    return extensions.plugin_install(conversation, package_digest, request_id)


@frappe.whitelist(methods=["POST"])
def plugin_toggle(conversation, installation, expected_revision, enabled):
    from zebra_erpnext import extensions

    return extensions.plugin_toggle(conversation, installation, expected_revision, enabled)


@frappe.whitelist(methods=["GET", "POST"])
def schedule_inventory(conversation):
    from zebra_erpnext import schedules

    return schedules.inventory(conversation)


@frappe.whitelist(methods=["POST"])
def schedule_create(conversation, title, prompt, trigger, request_id, timezone="Asia/Shanghai"):
    from zebra_erpnext import schedules

    return schedules.create(conversation, title, prompt, trigger, request_id, timezone)


@frappe.whitelist(methods=["GET", "POST"])
def schedule_detail(conversation, name):
    from zebra_erpnext import schedules

    return schedules.detail(conversation, name)


@frappe.whitelist(methods=["POST"])
def schedule_action(conversation, name, operation, schedule_version):
    from zebra_erpnext import schedules

    return schedules.action(conversation, name, operation, schedule_version)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def schedule_exchange():
    from zebra_erpnext.schedule_authority import exchange

    return exchange()
