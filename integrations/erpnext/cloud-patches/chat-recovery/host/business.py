"""Bounded native operations, preserving user/document/field permissions and approvals."""

import hashlib
import hmac
import json
import secrets
from datetime import timedelta
from html import escape

import frappe
from frappe.utils import get_datetime, now_datetime

from zebra_erpnext.business_attachments import attachment as attachment
from zebra_erpnext.business_attachments import checked_file as checked_file
from zebra_erpnext.business_documents import check_company as check_company
from zebra_erpnext.business_documents import checked_values as checked_values
from zebra_erpnext.business_documents import clean_document as clean_document
from zebra_erpnext.business_documents import document as document
from zebra_erpnext.business_documents import serialized as serialized
from zebra_erpnext.business_documents import validate as validate
from zebra_erpnext.business_native_actions import invoke_action as invoke_action
from zebra_erpnext.business_queries import aggregate as aggregate
from zebra_erpnext.business_queries import export as export
from zebra_erpnext.business_queries import query as query
from zebra_erpnext.business_queries import query_page as query_page
from zebra_erpnext.business_queries import read as read
from zebra_erpnext.business_queries import report_describe as report_describe
from zebra_erpnext.capabilities import SETTINGS_FIELDS, authenticated, meta_for, mutable

APPROVAL = "Zebra Business Approval"
READS = {
    "query",
    "get",
    "workflow_transitions",
    "report",
    "print",
    "files",
    "download_file",
    "query_page",
    "export",
    "aggregate",
    "report_describe",
}
WRITES = {
    "create",
    "update",
    "submit",
    "cancel",
    "delete",
    "amend",
    "workflow",
    "action",
    "create_from_action",
    "settings_update",
    "upload_file",
    "attach_file",
    "remove_file",
    "comment",
}
AGGREGATE_METRICS = {"count", "sum", "avg", "min", "max"}
SCHEMAS = {
    "query_page": (
        {"doctype"},
        {"doctype", "fields", "filters", "limit", "start", "company", "order_by"},
    ),
    "export": (
        {"doctype", "fields"},
        {"doctype", "fields", "filters", "limit", "start", "company", "order_by"},
    ),
    "aggregate": ({"doctype", "metric"}, {"doctype", "metric", "field", "filters", "company"}),
    "report_describe": ({"report"}, {"report", "company"}),
    "comment": (
        {"doctype", "name", "modified", "text"},
        {"doctype", "name", "modified", "text", "company"},
    ),
    "create_from_action": (
        {"doctype", "name", "modified", "action"},
        {"doctype", "name", "modified", "action", "company"},
    ),
    "settings_update": (
        {"doctype", "name", "values", "modified"},
        {"doctype", "name", "values", "modified", "company"},
    ),
    "upload_file": (
        {"doctype", "name", "modified", "filename", "content_base64"},
        {"doctype", "name", "modified", "filename", "content_base64", "company"},
    ),
    "attach_file": (
        {"doctype", "name", "modified", "file"},
        {"doctype", "name", "modified", "file", "company"},
    ),
    "remove_file": (
        {"doctype", "name", "modified", "file"},
        {"doctype", "name", "modified", "file", "company"},
    ),
    "download_file": ({"doctype", "name", "file"}, {"doctype", "name", "file", "company"}),
    "query": (
        {"doctype"},
        {"doctype", "fields", "filters", "limit", "start", "company", "order_by"},
    ),
    "get": ({"doctype", "name"}, {"doctype", "name", "company"}),
    "create": ({"doctype", "values"}, {"doctype", "values", "company"}),
    "update": (
        {"doctype", "name", "values", "modified"},
        {"doctype", "name", "values", "modified", "company"},
    ),
    "submit": ({"doctype", "name", "modified"}, {"doctype", "name", "modified", "company"}),
    "cancel": ({"doctype", "name", "modified"}, {"doctype", "name", "modified", "company"}),
    "delete": ({"doctype", "name", "modified"}, {"doctype", "name", "modified", "company"}),
    "amend": ({"doctype", "name", "modified"}, {"doctype", "name", "modified", "company"}),
    "workflow_transitions": ({"doctype", "name"}, {"doctype", "name", "company"}),
    "workflow": (
        {"doctype", "name", "modified", "action"},
        {"doctype", "name", "modified", "action", "company"},
    ),
    "report": ({"report"}, {"report", "filters", "company"}),
    "print": ({"doctype", "name"}, {"doctype", "name", "company", "format"}),
    "files": ({"doctype", "name"}, {"doctype", "name", "company"}),
    "action": (
        {"doctype", "name", "modified", "action"},
        {"doctype", "name", "modified", "action", "parameters", "company"},
    ),
}
SYSTEM_FIELDS = {
    "doctype",
    "name",
    "owner",
    "creation",
    "modified",
    "modified_by",
    "docstatus",
    "idx",
}
FORBIDDEN = {
    "flags",
    "ignore_permissions",
    "ignore_links",
    "ignore_mandatory",
    "ignore_validate",
    "ignore_user_permissions",
    "user",
    "run_as",
    "parent",
    "parenttype",
    "parentfield",
}


def fail(message, permission=False):
    frappe.throw(message, frappe.PermissionError if permission else frappe.ValidationError)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def bounded(value):
    """Fail closed before committing a mutation if its response cannot be recorded safely."""
    result = json.loads(frappe.as_json(value))
    if len(canonical(result).encode()) > 200000:
        fail("Result exceeds 200 KB. Request fewer records or a smaller report.")
    return result


def write(operation, args):
    meta = meta_for(args["doctype"])
    if not mutable(meta) and not (operation == "settings_update" and meta.name in SETTINGS_FIELDS):
        fail(
            "Administrative or Single DocType mutations require the native ERPNext interface", True
        )
    if operation == "create":
        if meta.name == "Company" and args.get("company"):
            fail(
                (
                    "Creating a Company requires a separate administrative workflow "
                    "outside the selected "
                    "company"
                ),
                True,
            )
        if not frappe.has_permission(meta.name, "create"):
            fail("Create is not permitted", True)
        values = checked_values(meta, args["values"])
        if args.get("company") and meta.has_field("company"):
            if values.get("company", args["company"]) != args["company"]:
                fail("Company does not match approval", True)
            values["company"] = args["company"]
        doc = frappe.get_doc(dict(values, doctype=meta.name))
        check_company(doc, args.get("company"))
        doc.insert()
        check_company(doc, args.get("company"))
        return serialized(doc)
    permission = {
        "comment": "write",
        "settings_update": "write",
        "upload_file": "write",
        "attach_file": "write",
        "remove_file": "write",
        "create_from_action": "read",
        "update": "write",
        "workflow": "write",
        "amend": "amend",
        "action": "read",
    }.get(operation, operation)
    doc = document(args, permission, lock=True)
    if operation == "comment":
        text = args["text"]
        if not isinstance(text, str) or not text.strip() or len(text) > 5000:
            fail("Comment must contain 1 to 5000 characters")
        comment = doc.add_comment("Comment", text=escape(text).replace("\n", "<br>"))
        return {"name": comment.name, "reference_doctype": doc.doctype, "reference_name": doc.name}
    if operation in {"upload_file", "attach_file", "remove_file"}:
        return attachment(operation, args, doc)
    if operation == "settings_update":
        if (
            not isinstance(args["values"], dict)
            or not args["values"].keys() <= SETTINGS_FIELDS[meta.name]
        ):
            fail("Only published locale/format settings may be changed", True)
        doc.update(checked_values(meta, args["values"], existing=doc))
        doc.save()
    elif operation == "update":
        doc.update(checked_values(meta, args["values"], existing=doc))
        check_company(doc, args.get("company"))
        doc.save()
    elif operation == "submit":
        if not meta.is_submittable:
            fail("DocType is not submittable")
        doc.submit()
    elif operation == "cancel":
        if not meta.is_submittable:
            fail("DocType is not submittable")
        doc.cancel()
    elif operation == "delete":
        frappe.delete_doc(doc.doctype, doc.name)
        return {"deleted": True, "doctype": doc.doctype, "name": doc.name}
    elif operation == "amend":
        if (
            not meta.is_submittable
            or doc.docstatus != 2
            or not frappe.has_permission(meta.name, "create")
        ):
            fail("Only cancelled, amendable documents can be amended", True)
        amended = frappe.copy_doc(doc)
        amended.docstatus = 0
        amended.amended_from = doc.name
        amended.insert()
        doc = amended
    elif operation == "workflow":
        from frappe.model.workflow import apply_workflow

        doc = apply_workflow(doc.as_dict(), args["action"])
    elif operation in {"action", "create_from_action"}:
        return invoke_action(doc, args, persist=operation == "create_from_action")
    return serialized(doc)


def binding(operation, args, request_id):
    return hashlib.sha256(
        canonical(
            {
                "user": frappe.session.user,
                "operation": operation,
                "arguments": args,
                "request_id": request_id,
            }
        ).encode()
    ).hexdigest()


def proposal(operation, args, request_id, digest, request_key):
    token = secrets.token_hex(32)
    record = frappe.get_doc(
        {
            "doctype": APPROVAL,
            "name": hashlib.sha256(token.encode()).hexdigest(),
            "user": frappe.session.user,
            "operation": operation,
            "arguments_json": canonical(args),
            "request_id": request_id,
            "company": args.get("company"),
            "digest": digest,
            "request_key": request_key,
            "expires_at": now_datetime() + timedelta(minutes=10),
            "status": "Pending",
        }
    )
    # Internal control record: never grant business users write access to approvals.
    record.db_insert()
    return {
        "approval_required": True,
        "proposal_id": record.name,
        "approval_token": token,
        "operation": operation,
        "arguments": args,
        "request_id": request_id,
        "expires_at": str(record.expires_at),
    }


@frappe.whitelist(methods=["POST"])
def execute(operation, arguments, request_id, approval_token=None):
    authenticated()
    if approval_token and frappe.flags.get("zebra_tool_call"):
        fail("Tools cannot confirm business approvals", True)
    args = validate(operation, arguments)
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 140:
        fail("request_id must contain 1 to 140 characters")
    if operation in READS:
        if approval_token:
            fail("Read operations do not accept approval tokens")
        return bounded(read(operation, args))
    digest = binding(operation, args, request_id)
    request_key = hashlib.sha256((frappe.session.user + "\n" + request_id).encode()).hexdigest()
    if not approval_token:
        prior = frappe.db.get_value(
            APPROVAL,
            {"request_key": request_key},
            ["digest", "status", "result_json"],
            as_dict=True,
        )
        if prior:
            if prior.digest != digest:
                fail("request_id was already used for different arguments")
            if prior.status == "Completed":
                return json.loads(prior.result_json)
            fail("Approval is already pending. Use its token or start with a new request_id.")
        # Validate target permissions before proposing; full validation repeats on confirmation.
        meta = meta_for(args["doctype"])
        if not mutable(meta) and not (
            operation == "settings_update" and meta.name in SETTINGS_FIELDS
        ):
            fail("This DocType cannot be mutated through the agent", True)
        if operation == "create":
            if meta.name == "Company" and args.get("company"):
                fail(
                    (
                        "Creating a Company requires a separate administrative workflow "
                        "outside the selected "
                        "company"
                    ),
                    True,
                )
            if not frappe.has_permission(meta.name, "create"):
                fail("Create is not permitted", True)
            checked_values(meta, args["values"])
        else:
            document(
                args,
                {
                    "comment": "write",
                    "settings_update": "write",
                    "upload_file": "write",
                    "attach_file": "write",
                    "remove_file": "write",
                    "create_from_action": "read",
                    "update": "write",
                    "workflow": "write",
                    "amend": "amend",
                    "action": "read",
                }.get(operation, operation),
            )
        return proposal(operation, args, request_id, digest, request_key)
    browser_confirmation()
    if not isinstance(approval_token, str) or len(approval_token) != 64:
        fail("Invalid approval token", True)
    name = hashlib.sha256(approval_token.encode()).hexdigest()
    # Lock is retained until the request transaction commits or rolls back; result and
    # mutation commit together.
    row = frappe.db.get_value(
        APPROVAL,
        name,
        ["user", "digest", "request_key", "expires_at", "status", "result_json"],
        as_dict=True,
        for_update=True,
    )
    if (
        not row
        or row.user != frappe.session.user
        or row.digest != digest
        or row.request_key != request_key
    ):
        fail("Approval does not match this user, request or arguments", True)
    if row.status == "Completed":
        return json.loads(row.result_json)
    if row.status != "Pending" or get_datetime(row.expires_at) <= now_datetime():
        fail("Approval has expired or is unavailable", True)
    return complete_approval(name, operation, args)


def browser_confirmation():
    """Require the independent authenticated human session, even when site CSRF is disabled."""
    authenticated()
    request = getattr(frappe.local, "request", None)
    saved = frappe.session.data.get("csrf_token")
    supplied = frappe.get_request_header("X-Frappe-CSRF-Token")
    if (
        frappe.flags.get("zebra_tool_call")
        or not request
        or request.method != "POST"
        or frappe.get_request_header("Authorization")
        or not request.cookies.get("sid")
        or request.cookies.get("sid") != frappe.session.sid
        or not isinstance(saved, str)
        or not isinstance(supplied, str)
        or not hmac.compare_digest(saved, supplied)
    ):
        fail("Approval requires a signed-in browser session and CSRF token", True)


@frappe.whitelist(methods=["POST"])
def confirm(proposal_id):
    browser_confirmation()
    if not isinstance(proposal_id, str) or len(proposal_id) != 64:
        fail("Invalid proposal id")
    row = frappe.db.get_value(
        APPROVAL,
        proposal_id,
        [
            "user",
            "operation",
            "arguments_json",
            "request_id",
            "digest",
            "expires_at",
            "status",
            "result_json",
        ],
        as_dict=True,
        for_update=True,
    )
    if not row or row.user != frappe.session.user:
        fail("Approval is not available to this user", True)
    if row.status == "Completed":
        return json.loads(row.result_json)
    if row.status != "Pending" or get_datetime(row.expires_at) <= now_datetime():
        fail("Approval has expired or is unavailable", True)
    args = validate(row.operation, row.arguments_json)
    if row.operation not in WRITES or binding(row.operation, args, row.request_id) != row.digest:
        fail("Approval payload is invalid", True)
    return complete_approval(proposal_id, row.operation, args)


def complete_approval(name, operation, args):
    # Reuse Frappe's document-hook transaction guard so native methods cannot commit before
    # the receipt.
    frappe.db._disable_transaction_control += 1
    try:
        result = bounded(write(operation, args))
        frappe.db.set_value(
            APPROVAL, name, {"status": "Completed", "result_json": canonical(result)}
        )
        return result
    finally:
        frappe.db._disable_transaction_control -= 1
