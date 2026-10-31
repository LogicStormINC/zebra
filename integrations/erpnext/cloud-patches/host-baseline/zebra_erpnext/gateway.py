"""Declared Host tools with signed workload identity and mapped user delegation."""

import hashlib
import hmac
import json

import frappe
from frappe.utils import get_datetime, now_datetime
from werkzeug.wrappers import Response

from zebra_erpnext import cloud


def raw(value):
    return Response(frappe.as_json(value), content_type="application/json")


def delegated():
    settings = cloud.config()
    request = frappe.local.request
    headers = request.headers
    expected = {
        "X-Zebra-Host-App": "erpnext",
        "X-Zebra-Namespace": "erpnext",
        "X-Zebra-Workload-Identity": "erpnext-worker",
    }
    if any(headers.get(key) != value for key, value in expected.items()):
        frappe.throw("Workload not authorized", frappe.PermissionError)
    grant_id = headers.get("X-Zebra-Grant-Id", "")
    record = frappe.db.get_value(
        "Zebra Grant",
        grant_id,
        [("user"), ("company"), ("conversation"), ("expires_at"), ("run_id"), ("workspace_ref")],
        as_dict=True,
    )
    if (
        not record
        or get_datetime(record.expires_at) <= now_datetime()
        or headers.get("X-Zebra-Workspace-Ref") != record.workspace_ref
    ):
        frappe.throw("Delegation expired", frappe.PermissionError)
    body = request.get_json(silent=True) or {}
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # The deployed Cloud image uses these fixed signed paths. Caddy rewrites
    # them to Frappe RPCs; derive the original path from the authenticated body,
    # never from a browser-supplied forwarding header.
    signed_path = (
        ("/manifest")
        if request.method == ("GET")
        else ("/tools/") + str(body.get(("toolName"), (""))) + ("/invoke")
    )
    canonical = "\n".join(
        [
            request.method.upper(),
            signed_path,
            grant_id,
            record.workspace_ref,
            "erpnext",
            "erpnext",
            encoded,
        ]
    )
    signature = hmac.new(
        settings[("host_secret")].encode(), canonical.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, headers.get("X-Zebra-Host-Auth", "")):
        frappe.throw("Workload signature invalid", frappe.PermissionError)
    if not frappe.db.get_value("User", record.user, "enabled"):
        frappe.throw("User disabled", frappe.PermissionError)
    return record, body


@frappe.whitelist(allow_guest=True, methods=["GET"])
def jwks():
    settings = cloud.config()
    with open(settings["jwks_file"], encoding="utf-8") as file:
        return raw(json.load(file))


@frappe.whitelist(allow_guest=True, methods=["GET"])
def manifest():
    delegated()
    from zebra_erpnext.business import READS, WRITES

    tools = []
    for name, description, properties, required in [
        (
            ("erpnext.discover"),
            (
                "Discover installed ERPNext DocTypes, fields, reports, operations"
                " and business actions permitted to the current user. Use before "
                "a new business operation."
            ),
            {
                "query": {"type": "string"},
                "doctype": {"type": "string"},
                "start": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            [],
        ),
        (
            ("erpnext.read"),
            (
                "Read ERPNext data through native user, document, field and compa"
                "ny permissions. Use discover to learn fields. Query/paginate/agg"
                "regate/export/get/report/report_describe/print/files/workflow re"
                "ads; never raw SQL."
            ),
            {
                ("operation"): {("type"): ("string"), ("enum"): sorted(READS)},
                ("arguments"): {("type"): ("object")},
            },
            [("operation"), ("arguments")],
        ),
        (
            ("erpnext.propose"),
            (
                "Propose a native ERPNext business operation. Returns approval_re"
                "quired and proposal_id; user must confirm independently in the a"
                "ssistant panel. Never claim it executed until result reports com"
                "pleted. Reuse the returned request_id with identical arguments t"
                "o read its result after approval."
            ),
            {
                "operation": {"type": "string", "enum": sorted(WRITES)},
                "arguments": {"type": "object"},
                "request_id": {"type": "string"},
            },
            ["operation", "arguments"],
        ),
    ]:
        tools.append(
            dict(
                name=name,
                description=description,
                requiredArguments=required,
                argumentProperties=properties,
                executionLocation="host",
                scopes=["erpnext.read"],
                risk="read",
                parallelSafe=False,
                idempotency="none",
                resourceBindings=[],
                maxOutputBytes=262144,
            )
        )
    return raw(dict(workloadIdentity="erpnext-worker", bindingPolicy="declared", tools=tools))


@frappe.whitelist(allow_guest=True, methods=["POST"])
def invoke():
    record, body = delegated()
    conversation = frappe.get_doc("Zebra Conversation", record.conversation)
    if (
        not record.run_id
        or record.run_id != conversation.active_run_id
        or conversation.status not in {"dispatching", "running"}
    ):
        frappe.throw("Execution delegation is no longer active", frappe.PermissionError)
    old_user = frappe.session.user
    try:
        frappe.set_user(record.user)
        frappe.get_doc("Company", record.company).check_permission("read")
        frappe.flags.zebra_tool_call = True
        from zebra_erpnext import business, capabilities

        name, args = body.get("toolName"), body.get("arguments") or {}
        if not isinstance(args, dict):
            frappe.throw("Invalid tool arguments")
        if name == "erpnext.discover":
            if set(args) - {"query", "doctype", "start", "limit"}:
                frappe.throw("Unsupported discovery arguments")
            result = capabilities.discover(**args)
        elif name in {"erpnext.read", "erpnext.propose"}:
            if set(args) - {"operation", "arguments", "request_id"}:
                frappe.throw("Unsupported tool arguments")
            operation = args.get("operation")
            allowed = business.READS if name == "erpnext.read" else business.WRITES
            if operation not in allowed:
                frappe.throw("Operation not in published tool")
            values = args.get("arguments") or {}
            if not isinstance(values, dict) or "approval_token" in values:
                frappe.throw("Invalid business arguments")
            if values.get("company") and values["company"] != record.company:
                frappe.throw("Company is outside conversation scope", frappe.PermissionError)
            values = {**values, "company": record.company}
            request_id = (
                args.get("request_id")
                or hashlib.sha256(
                    (record.user + ":" + str(body.get("toolCallId", ""))).encode()
                ).hexdigest()
            )
            result = business.execute(operation, values, request_id)
            if isinstance(result, dict):
                result.pop("approval_token", None)
                result["request_id"] = request_id
                if result.get("proposal_id"):
                    frappe.db.set_value(
                        "Zebra Business Approval",
                        result["proposal_id"],
                        {("conversation"): record.conversation, ("run_id"): record.run_id},
                        update_modified=False,
                    )
        else:
            frappe.throw("Unknown Host tool")
        return raw({"output": frappe.as_json(result)})
    finally:
        frappe.flags.zebra_tool_call = False
        frappe.set_user(old_user)
