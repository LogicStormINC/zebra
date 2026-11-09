"""Declared Host tools with signed workload identity and mapped user delegation."""

import hashlib
import hmac
import json

import frappe
from frappe.utils import get_datetime, now_datetime
from werkzeug.wrappers import Response

from zebra_erpnext import cloud

CHAT_READS = {"get", "query", "query_page", "aggregate", "report_describe", "workflow_transitions"}


def business_arguments_schema(operations):
    """Publish the existing validator's exact key sets for the bounded chat tools."""
    from zebra_erpnext.business import AGGREGATE_METRICS, SCHEMAS

    text = {"type": "string", "minLength": 1, "maxLength": 140}
    fields = {key: text for key in ("doctype", "name", "modified", "company", "report")}
    fields.update(
        fields={"type": "array", "minItems": 1, "maxItems": 30, "items": {"type": "string"}},
        filters={
            "type": "object",
            "description": "Readable field names and native filter values; never SQL.",
        },
        limit={"type": "integer", "minimum": 1, "maximum": 50},
        start={"type": "integer", "minimum": 0, "maximum": 10000},
        order_by={
            "type": "string",
            "maxLength": 300,
            "description": "At most three readable field asc/desc terms.",
        },
        metric={"type": "string", "enum": sorted(AGGREGATE_METRICS)},
        field={
            "type": "string",
            "description": "Readable numeric field for sum/avg/min/max; omit for count.",
        },
        values={
            "type": "object",
            "minProperties": 1,
            "description": (
                "Native writable fields; child tables use native field names learned from discover."
            ),
        },
    )
    variants = []
    for operation in sorted(operations):
        required, allowed = SCHEMAS[operation]
        properties = {key: fields[key] for key in sorted(allowed)}
        if operation == "aggregate":
            variants.append(
                {
                    "properties": {
                        key: value for key, value in properties.items() if key != "field"
                    }
                    | {"metric": {"type": "string", "enum": ["count"]}},
                    "required": sorted(required),
                    "additionalProperties": False,
                }
            )
            properties = properties | {
                "metric": {"type": "string", "enum": sorted(AGGREGATE_METRICS - {"count"})}
            }
            required = required | {"field"}
        variants.append(
            {"properties": properties, "required": sorted(required), "additionalProperties": False}
        )
    keys = set().union(*(SCHEMAS[operation][1] for operation in operations))
    return {
        "type": "object",
        "properties": {key: fields[key] for key in sorted(keys)},
        "anyOf": variants,
        "additionalProperties": False,
    }


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
        ["user", "company", "conversation", "expires_at", "run_id", "workspace_ref"],
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
        "/manifest"
        if request.method == "GET"
        else "/tools/" + str(body.get("toolName", "")) + "/invoke"
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
        settings["host_secret"].encode(), canonical.encode(), hashlib.sha256
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

    readonly_chat = cloud.config().get("chat_readonly_enabled") is True
    plan_proposals = (
        readonly_chat and cloud.config().get("production_plan_proposals_enabled") is True
    )
    tools = []
    for name, description, properties, required in [
        (
            "erpnext.discover",
            (
                "Discover installed ERPNext DocTypes, fields, reports, operations and "
                "business actions permitted to the current user. Use before a new "
                "business operation."
            ),
            {
                "query": {"type": "string"},
                "doctype": {"type": "string"},
                "start": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            [],
        ),
        (
            "erpnext.read",
            (
                "Read ERPNext data through native user, document, field and company "
                "permissions. Use discover to learn fields. "
                "Query/paginate/aggregate/export/get/report/report_describe/print/files"
                "/workflow reads; never raw "
                "SQL."
            ),
            {
                "operation": {"type": "string", "enum": sorted(READS)},
                "arguments": {"type": "object"},
            },
            ["operation", "arguments"],
        ),
        (
            "erpnext.propose",
            (
                "Propose a native ERPNext business operation. Returns "
                "approval_required and proposal_id; user must confirm independently in "
                "the assistant panel. Never claim it executed until result reports "
                "completed. Reuse the returned request_id with identical arguments to "
                "read its result after "
                "approval."
            ),
            {
                "operation": {"type": "string", "enum": sorted(WRITES)},
                "arguments": {"type": "object"},
                "request_id": {"type": "string"},
            },
            ["operation", "arguments"],
        ),
    ]:
        if readonly_chat and name == "erpnext.propose":
            if not plan_proposals:
                continue
            properties = {
                **properties,
                "operation": {"type": "string", "enum": ["create", "submit", "update"]},
                "arguments": business_arguments_schema({"create", "update", "submit"}),
                "request_id": {"type": "string", "minLength": 1, "maxLength": 140},
            }
            properties["arguments"]["properties"]["doctype"] = {
                "type": "string",
                "enum": ["Production Plan"],
            }
            description = (
                "Prepare only Production Plan create/update/submit for independent "
                "human confirmation. This does not execute a business write. Never "
                "confirm your own proposal; the user must click the exact-arguments "
                "confirmation in the assistant panel. Only after that confirmation, "
                "reuse the returned request_id with identical arguments to read its "
                "completed "
                "result."
            )
        if readonly_chat and name == "erpnext.read":
            properties = {
                **properties,
                "operation": {"type": "string", "enum": sorted(CHAT_READS)},
                "arguments": business_arguments_schema(CHAT_READS),
            }
            description = (
                "Read permitted ERP data only. Query/query_page require doctype; "
                "get/workflow_transitions require doctype+name; aggregate requires "
                "doctype+metric (sum/avg/min/max also require numeric field); "
                "report_describe requires report. Query limit is 1..50; aggregate "
                "takes no limit or group_by and scans at most 1000 accessible rows. "
                'Examples: operation="query", arguments={"doctype":"Company","fields":['
                '"name"],"limit":20}; operation="aggregate", '
                'arguments={"doctype":"Sales Order","metric":"count"}. For count omit '
                "field. No files, exports or business "
                "mutation."
            )
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
                maxOutputBytes=8192 if readonly_chat else 262144,
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
        conversation = cloud.owned(record.conversation)
        if (
            conversation.company != record.company
            or conversation.workspace_ref != record.workspace_ref
        ):
            frappe.throw("Delegation scope changed", frappe.PermissionError)
        frappe.get_doc("Company", record.company).check_permission("read")
        if body.get("toolName") == "erpnext.authority":
            from zebra_erpnext.authority import check

            return raw({"output": frappe.as_json(check(record, body.get("arguments")))})
        readonly_chat = cloud.config().get("chat_readonly_enabled") is True
        plan_proposals = (
            readonly_chat and cloud.config().get("production_plan_proposals_enabled") is True
        )
        if readonly_chat and (
            body.get("toolName")
            not in (
                {"erpnext.discover", "erpnext.read", "erpnext.propose"}
                if plan_proposals
                else {"erpnext.discover", "erpnext.read"}
            )
            or body.get("toolName") == "erpnext.read"
            and (body.get("arguments") or {}).get("operation") not in CHAT_READS
        ):
            frappe.throw("当前仅支持 ERP 只读查询。", frappe.PermissionError)
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
            if (
                readonly_chat
                and name == "erpnext.propose"
                and (
                    operation not in {"create", "update", "submit"}
                    or values.get("doctype") != "Production Plan"
                )
            ):
                frappe.throw(
                    "Only Production Plan create/update/submit proposals are enabled",
                    frappe.PermissionError,
                )
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
                        {"conversation": record.conversation, "run_id": record.run_id},
                        update_modified=False,
                    )
        else:
            frappe.throw("Unknown Host tool")
        output = frappe.as_json(result)
        if readonly_chat and len(output.encode()) > 8192:
            output = frappe.as_json(
                {"status": "too_large", "message": "查询结果较大，请缩小字段或条件。"}
            )
        return raw({"output": output})
    finally:
        frappe.flags.zebra_tool_call = False
        frappe.set_user(old_user)
