"""Bounded native operations, preserving user/document/field permissions and approvals."""
import csv
import io
from decimal import Decimal, InvalidOperation
from html import escape
import hashlib
import base64
import binascii
from pathlib import PurePath
import inspect
import hmac
import json
import secrets
from datetime import timedelta

import frappe
from frappe.utils import get_datetime, now_datetime

from zebra_erpnext.capabilities import (
    authenticated, meta_for, mutable, published_actions, readable_fields, permitted_fields, SETTINGS_FIELDS,
)

APPROVAL = "Zebra Business Approval"
READS = {"query", "get", "workflow_transitions", "report", "print", "files", "download_file", "query_page", "export", "aggregate", "report_describe"}
WRITES = {"create", "update", "submit", "cancel", "delete", "amend", "workflow", "action", "create_from_action", "settings_update", "upload_file", "attach_file", "remove_file", "comment"}
AGGREGATE_METRICS = {"count", "sum", "avg", "min", "max"}
SCHEMAS = {
    "query_page": ({"doctype"}, {"doctype", "fields", "filters", "limit", "start", "company", "order_by"}),
    "export": ({"doctype", "fields"}, {"doctype", "fields", "filters", "limit", "start", "company", "order_by"}),
    "aggregate": ({"doctype", "metric"}, {"doctype", "metric", "field", "filters", "company"}),
    "report_describe": ({"report"}, {"report", "company"}),
    "comment": ({"doctype", "name", "modified", "text"}, {"doctype", "name", "modified", "text", "company"}),
    "create_from_action": ({"doctype", "name", "modified", "action"}, {"doctype", "name", "modified", "action", "company"}),
    "settings_update": ({"doctype", "name", "values", "modified"}, {"doctype", "name", "values", "modified", "company"}),
    "upload_file": ({"doctype", "name", "modified", "filename", "content_base64"}, {"doctype", "name", "modified", "filename", "content_base64", "company"}),
    "attach_file": ({"doctype", "name", "modified", "file"}, {"doctype", "name", "modified", "file", "company"}),
    "remove_file": ({"doctype", "name", "modified", "file"}, {"doctype", "name", "modified", "file", "company"}),
    "download_file": ({"doctype", "name", "file"}, {"doctype", "name", "file", "company"}),
    "query": ({"doctype"}, {"doctype", "fields", "filters", "limit", "start", "company", "order_by"}),
    "get": ({"doctype", "name"}, {"doctype", "name", "company"}),
    "create": ({"doctype", "values"}, {"doctype", "values", "company"}),
    "update": ({"doctype", "name", "values", "modified"}, {"doctype", "name", "values", "modified", "company"}),
    "submit": ({"doctype", "name", "modified"}, {"doctype", "name", "modified", "company"}),
    "cancel": ({"doctype", "name", "modified"}, {"doctype", "name", "modified", "company"}),
    "delete": ({"doctype", "name", "modified"}, {"doctype", "name", "modified", "company"}),
    "amend": ({"doctype", "name", "modified"}, {"doctype", "name", "modified", "company"}),
    "workflow_transitions": ({"doctype", "name"}, {"doctype", "name", "company"}),
    "workflow": ({"doctype", "name", "modified", "action"}, {"doctype", "name", "modified", "action", "company"}),
    "report": ({"report"}, {"report", "filters", "company"}),
    "print": ({"doctype", "name"}, {"doctype", "name", "company", "format"}),
    "files": ({"doctype", "name"}, {"doctype", "name", "company"}),
    "action": ({"doctype", "name", "modified", "action"}, {"doctype", "name", "modified", "action", "parameters", "company"}),
}
SYSTEM_FIELDS = {"doctype", "name", "owner", "creation", "modified", "modified_by", "docstatus", "idx"}
FORBIDDEN = {"flags", "ignore_permissions", "ignore_links", "ignore_mandatory", "ignore_validate",
             "ignore_user_permissions", "user", "run_as", "parent", "parenttype", "parentfield"}


def fail(message, permission=False):
    frappe.throw(message, frappe.PermissionError if permission else frappe.ValidationError)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def bounded(value):
    """Fail closed before committing a mutation if its response cannot be recorded safely."""
    result = json.loads(frappe.as_json(value))
    if len(canonical(result).encode()) > 200000:
        fail("Result exceeds 200 KB. Request fewer records or a smaller report.")
    return result


def validate(operation, arguments):
    if operation not in SCHEMAS:
        fail("Unsupported business operation")
    args = frappe.parse_json(arguments) if isinstance(arguments, str) else arguments
    if not isinstance(args, dict):
        fail("arguments must be an object")
    if ((frappe.conf.get('zebra_agent') or {}).get('production_plan_proposals_enabled') is True
            and operation in WRITES and (operation not in {'create', 'update', 'submit'}
                or args.get('doctype') != 'Production Plan')):
        fail("Only Production Plan create/update/submit may be proposed or confirmed", True)
    required, allowed = SCHEMAS[operation]
    if required - args.keys() or args.keys() - allowed:
        fail("Missing or unsupported operation arguments")
    try:
        encoded = canonical(args)
    except (ValueError, TypeError):
        fail("Arguments must contain finite JSON values")
    if len(encoded.encode()) > (800000 if operation == "upload_file" else 100000):
        fail("Arguments exceed the operation size limit")
    for key in ("doctype", "name", "modified", "company", "report", "action", "format", "file", "filename"):
        if key in args and (not isinstance(args[key], str) or not args[key] or len(args[key]) > 140):
            fail("Invalid " + key)
    if args.get("company") and not frappe.get_list("Company", filters={"name": args["company"]}, fields=["name"], limit_page_length=1):
        fail("Company is not accessible", True)
    if operation == "settings_update" and (args["doctype"] not in SETTINGS_FIELDS
            or args["name"] != args["doctype"] or not isinstance(args["values"], dict)
            or not args["values"] or not args["values"].keys() <= SETTINGS_FIELDS[args["doctype"]]):
        fail("Only published locale/format settings may be changed", True)
    return args


def check_company(doc, company=None):
    actual = doc.name if doc.doctype == "Company" else (doc.get("company") if doc.meta.has_field("company") else None)
    if company and actual and actual != company:
        fail("Document is outside the approved company", True)
    if actual and not frappe.get_list("Company", filters={"name": actual}, fields=["name"], limit_page_length=1):
        fail("Document company is not accessible", True)


def document(args, permission="read", lock=False):
    meta_for(args["doctype"])
    doc = frappe.get_doc(args["doctype"], args["name"], for_update=lock)
    doc.check_permission(permission)
    check_company(doc, args.get("company"))
    if "modified" in args and str(doc.modified) != args["modified"]:
        fail("Document changed. Refresh and request a new approval.")
    return doc


def serialized(doc):
    doc.check_permission("read")
    doc.apply_fieldlevel_read_permissions()
    return clean_document(doc)


def clean_document(doc, parenttype=None):
    allowed = readable_fields(doc.meta, parenttype=parenttype) | SYSTEM_FIELDS
    data = doc.as_dict()
    result = {k: v for k, v in data.items() if k in allowed}
    for field in doc.meta.get_table_fields():
        if field.fieldname in result:
            result[field.fieldname] = [clean_document(child, doc.doctype) for child in doc.get(field.fieldname) or []]
    return result


def checked_values(meta, values, parenttype=None, existing=None):
    if not isinstance(values, dict) or not values:
        fail("values must be a nonempty object")
    allowed = permitted_fields(meta, parenttype, permission_type="write")
    cleaned = {}
    for key, value in values.items():
        field = meta.get_field(key)
        if key in SYSTEM_FIELDS | FORBIDDEN or key.startswith("_") or not field or key not in allowed or field.read_only or field.fieldtype == "Password":
            fail("Field is not writable: " + key, True)
        if field.fieldtype in {"Table", "Table MultiSelect"}:
            if not isinstance(value, list) or len(value) > 100:
                fail("Child table must contain at most 100 rows")
            child_meta = frappe.get_meta(field.options)
            existing_rows = {row.name: row for row in existing.get(key) or []} if existing else {}
            cleaned[key] = []
            seen = set()
            for row in value:
                if not isinstance(row, dict):
                    fail("Child rows must be objects")
                row = dict(row)
                name = row.pop("name", None)
                if name is not None and (not isinstance(name, str) or not name):
                    fail("Invalid child row name")
                original = existing_rows.get(name) if name else None
                if name and (not original or name in seen or original.parent != existing.name
                             or original.parenttype != meta.name or original.parentfield != key):
                    fail("Child row does not belong to this document and field", True)
                if name:
                    seen.add(name)
                changes = checked_values(child_meta, row, parenttype=meta.name, existing=original) if row else {}
                if not row and not original:
                    fail("New child rows must contain values")
                cleaned[key].append(dict(original.as_dict(), **changes) if original else changes)
        elif isinstance(value, (dict, list)):
            fail("Scalar field requires a scalar value: " + key)
        else:
            cleaned[key] = value
    return cleaned


def query(args, extra_row=False, max_rows=50):
    meta = meta_for(args["doctype"])
    if meta.issingle:
        fail("Use get for Single DocTypes")
    allowed = {name for name in readable_fields(meta) if meta.get_field(name).fieldtype not in {"Table", "Table MultiSelect"}} | {"name", "owner", "creation", "modified", "modified_by", "docstatus"}
    fields = args.get("fields", ["name", "modified"])
    if not isinstance(fields, list) or not fields or len(fields) > 30 or any(not isinstance(f, str) or f not in allowed or meta.get_field(f) and meta.get_field(f).fieldtype in {"Table", "Table MultiSelect"} for f in fields):
        fail("Query fields must be explicit readable scalar field names", True)
    filters = args.get("filters", {})
    if not isinstance(filters, dict) or any(k not in allowed for k in filters):
        fail("Filters must use readable field names", True)
    for value in filters.values():
        if isinstance(value, list):
            if len(value) != 2 or not isinstance(value[0], str) or value[0] not in {"=", "!=", ">", "<", ">=", "<=", "like", "not like", "in", "not in", "between", "is"}:
                fail("Unsupported filter operator")
            operator, operand = value
            if operator in {"in", "not in", "between"}:
                if not isinstance(operand, list) or not operand or len(operand) > 100 or any(isinstance(v, (dict, list)) for v in operand):
                    fail("Invalid filter operand")
                if operator == "between" and len(operand) != 2:
                    fail("between requires two filter values")
            elif isinstance(operand, (dict, list)):
                fail("Invalid filter operand")
        elif isinstance(value, dict):
            fail("Invalid filter value")
    filters = dict(filters)
    if args.get("company") and meta.name == "Company":
        filters["name"] = args["company"]
    elif args.get("company") and meta.has_field("company"):
        filters["company"] = args["company"]
    limit, start = args.get("limit", 20), args.get("start", 0)
    if type(limit) is not int or not 1 <= limit <= max_rows or type(start) is not int or not 0 <= start <= 10000:
        fail("Invalid query pagination")
    order_by = args.get("order_by", "modified desc, name asc")
    if not isinstance(order_by, str) or len(order_by) > 300:
        fail("Invalid query ordering")
    terms = [part.strip().split() for part in order_by.split(",")]
    if not 1 <= len(terms) <= 3 or any(len(term) not in {1, 2} or term[0] not in allowed
            or len(term) == 2 and term[1].lower() not in {"asc", "desc"} for term in terms):
        fail("Ordering must use readable scalar field names", True)
    # Native get_list adds match conditions, user permissions and field checks.
    return frappe.get_list(meta.name, fields=fields, filters=filters, limit_start=start,
                           limit_page_length=limit + int(extra_row), order_by=order_by)


def query_page(args):
    rows = query(args, extra_row=True)
    limit, start = args.get("limit", 20), args.get("start", 0)
    return {"rows": rows[:limit], "has_more": len(rows) > limit,
            "next_start": start + limit if len(rows) > limit else None}


def export(args):
    if not frappe.has_permission(args["doctype"], "export"):
        fail("Export is not permitted", True)
    page = query_page(args)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(args["fields"])
    for row in page["rows"]:
        # Spreadsheet applications interpret leading formula markers even in quoted CSV.
        writer.writerow([("'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value)
                         for value in (row.get(field) for field in args["fields"])])
    return {"content": stream.getvalue(), "content_type": "text/csv; charset=utf-8",
            "has_more": page["has_more"], "next_start": page["next_start"], "row_count": len(page["rows"])}


def aggregate(args):
    metric, field = args["metric"], args.get("field")
    if not isinstance(metric, str) or metric not in AGGREGATE_METRICS:
        fail("Unsupported aggregate metric")
    meta = meta_for(args["doctype"])
    if metric == "count":
        if field is not None:
            fail("count does not accept a field")
    elif not isinstance(field, str) or field not in readable_fields(meta) or meta.get_field(field).fieldtype not in {"Int", "Long Int", "Float", "Currency", "Percent"}:
        fail("Aggregate requires a readable numeric field", True)
    # ponytail: scan at most 1000 permission-filtered rows; larger analytics needs a reviewed native report.
    rows = query(dict(args, fields=[field or "name"], limit=1000), extra_row=True, max_rows=1000)
    if len(rows) > 1000:
        fail("Aggregate exceeds 1000 accessible rows. Narrow filters or use a native report.")
    value = len(rows)
    if metric != "count":
        try:
            values = [Decimal(str(row[field])) for row in rows if row.get(field) is not None]
            if any(not item.is_finite() for item in values):
                fail("Aggregate contains non-finite values")
            value = ({"sum": lambda: sum(values, Decimal(0)), "avg": lambda: sum(values) / len(values),
                      "min": lambda: min(values), "max": lambda: max(values)}[metric]() if values else None)
        except (InvalidOperation, ValueError, TypeError):
            fail("Aggregate contains invalid numeric values")
        value = str(value) if value is not None else None
    return {"metric": metric, "field": field, "value": value, "row_count": len(rows), "complete": True}


def report_describe(name):
    from frappe.desk.query_report import get_report_doc
    report = get_report_doc(name)
    keys = ("fieldname", "label", "fieldtype", "options", "reqd", "default")
    return {"name": name, "reference_report": report.name, "ref_doctype": report.ref_doctype,
            "report_type": report.report_type, "prepared_report": bool(report.prepared_report),
            "filters": [{key: row.get(key) for key in keys} for row in report.get("filters") or []],
            "columns": [{key: row.get(key) for key in keys if key not in {"reqd", "default"}} for row in report.get("columns") or []],
            "descriptor_complete": False,
            "reason": "Native report JavaScript may define additional filters/columns; use the report page for dynamic descriptors. Scripts and SQL are never returned."}


def read(operation, args):
    if operation == "query_page":
        return query_page(args)
    if operation == "export":
        return export(args)
    if operation == "aggregate":
        return aggregate(args)
    if operation == "report_describe":
        return report_describe(args["report"])
    if operation == "query":
        return query(args)
    if operation == "report":
        from frappe.desk.query_report import get_report_doc, run
        report = get_report_doc(args["report"])
        if report.report_type not in {"Query Report", "Script Report", "Custom Report"}:
            fail("Use the ERPNext report page for this report type")
        filters = args.get("filters", {})
        if not isinstance(filters, dict):
            fail("Report filters must be an object")
        if args.get("company"):
            filters = dict(filters, company=args["company"])
        return run(args["report"], filters=filters, are_default_filters=False)
    doc = document(args)
    if operation == "get":
        return serialized(doc)
    if operation == "workflow_transitions":
        from frappe.model.workflow import get_transitions, get_workflow_name
        return get_transitions(doc) if get_workflow_name(doc.doctype) else []
    if operation == "files":
        # File's native match conditions enforce private attachment access.
        return frappe.get_list("File", filters={"attached_to_doctype": doc.doctype, "attached_to_name": doc.name},
                               fields=["name", "file_name", "file_url", "is_private"], limit_page_length=50)
    if operation == "download_file":
        file = checked_file(args, doc, "download")
        return {"name": file.name, "file_name": file.file_name, "url": file.file_url, "is_private": bool(file.is_private)}
    if operation == "print":
        doc.check_permission("print")
        # Return the permission-checked native view URL, without running custom template code here.
        from urllib.parse import urlencode
        return {"url": "/printview?" + urlencode({"doctype": doc.doctype, "name": doc.name,
                                                   "format": args.get("format", "Standard")})}


def write(operation, args):
    meta = meta_for(args["doctype"])
    if not mutable(meta) and not (operation == "settings_update" and meta.name in SETTINGS_FIELDS):
        fail("Administrative or Single DocType mutations require the native ERPNext interface", True)
    if operation == "create":
        if meta.name == "Company" and args.get("company"):
            fail("Creating a Company requires a separate administrative workflow outside the selected company", True)
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
    permission = {"comment": "write", "settings_update": "write", "upload_file": "write", "attach_file": "write", "remove_file": "write", "create_from_action": "read", "update": "write", "workflow": "write", "amend": "amend", "action": "read"}.get(operation, operation)
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
        if not isinstance(args["values"], dict) or not args["values"].keys() <= SETTINGS_FIELDS[meta.name]:
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
        if not meta.is_submittable or doc.docstatus != 2 or not frappe.has_permission(meta.name, "create"):
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


def invoke_action(doc, args, persist=False):
    entry = published_actions(doc.doctype).get(args["action"])
    if not entry:
        fail("Business action is not explicitly published", True)
    doc.check_permission(entry["permission"])
    parameters = args.get("parameters", {})
    schema = entry.get("parameters", {})
    if not isinstance(parameters, dict) or not isinstance(schema, dict) or parameters.keys() != schema.keys():
        fail("Action parameters must exactly match the published schema")
    types = {"str": str, "int": int, "float": float, "bool": bool}
    for key, expected in schema.items():
        if key in FORBIDDEN | SYSTEM_FIELDS or key.startswith("_") or expected not in types or type(parameters[key]) is not types[expected]:
            fail("Invalid business action parameter: " + key)
    if entry.get("conversion"):
        function = frappe.get_attr(entry["conversion"])
        frappe.is_whitelisted(function)
        target = entry["target_doctype"]
        if not frappe.has_permission(target, "create") or not frappe.has_permission(target, "read"):
            fail("Conversion target is not accessible", True)
        draft = function(doc.doctype, doc.name) if args["action"].endswith(".make_payment_entry") else function(doc.name)
        if draft.doctype != target or not draft.is_new():
            fail("Business conversion must return an unsaved target draft")
        check_company(draft, args.get("company"))
        if persist:
            draft.insert()
            check_company(draft, args.get("company"))
            return {"saved": True, "target_doctype": target, "document": serialized(draft)}
        draft.apply_fieldlevel_read_permissions()
        return {"saved": False, "target_doctype": target, "document": clean_document(draft)}
    if persist:
        fail("Only reviewed native conversions may create mapped drafts", True)
    method_name = entry.get("method", "")
    if not method_name.isidentifier() or method_name.startswith("_"):
        fail("Invalid published controller method")
    method = getattr(doc, method_name, None)
    if not callable(method):
        fail("Published action method does not exist")
    function = getattr(method, "__func__", method)
    frappe.is_whitelisted(function)
    if "POST" not in frappe.allowed_http_methods_for_whitelisted_func.get(function, ()):
        fail("Published action does not allow POST", True)
    inspect.signature(method).bind(**parameters)
    # Only deployer-published controller actions, all confirmed, with native document checks.
    return method(**parameters)


def binding(operation, args, request_id):
    return hashlib.sha256(canonical({"user": frappe.session.user, "operation": operation,
                                     "arguments": args, "request_id": request_id}).encode()).hexdigest()


def proposal(operation, args, request_id, digest, request_key):
    token = secrets.token_hex(32)
    record = frappe.get_doc({"doctype": APPROVAL, "name": hashlib.sha256(token.encode()).hexdigest(),
                            "user": frappe.session.user, "operation": operation,
                            "arguments_json": canonical(args), "request_id": request_id,
                            "company": args.get("company"), "digest": digest,
                            "request_key": request_key, "expires_at": now_datetime() + timedelta(minutes=10),
                            "status": "Pending"})
    # Internal control record: never grant business users write access to approvals.
    record.db_insert()
    return {"approval_required": True, "proposal_id": record.name, "approval_token": token, "operation": operation,
            "arguments": args, "request_id": request_id, "expires_at": str(record.expires_at)}


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
        prior = frappe.db.get_value(APPROVAL, {"request_key": request_key}, ["digest", "status", "result_json"], as_dict=True)
        if prior:
            if prior.digest != digest:
                fail("request_id was already used for different arguments")
            if prior.status == "Completed":
                return json.loads(prior.result_json)
            fail("Approval is already pending. Use its token or start with a new request_id.")
        # Validate target permissions before proposing; full validation repeats on confirmation.
        meta = meta_for(args["doctype"])
        if not mutable(meta) and not (operation == "settings_update" and meta.name in SETTINGS_FIELDS):
            fail("This DocType cannot be mutated through the agent", True)
        if operation == "create":
            if meta.name == "Company" and args.get("company"):
                fail("Creating a Company requires a separate administrative workflow outside the selected company", True)
            if not frappe.has_permission(meta.name, "create"):
                fail("Create is not permitted", True)
            checked_values(meta, args["values"])
        else:
            document(args, {"comment": "write", "settings_update": "write", "upload_file": "write", "attach_file": "write", "remove_file": "write", "create_from_action": "read", "update": "write", "workflow": "write", "amend": "amend", "action": "read"}.get(operation, operation))
        return proposal(operation, args, request_id, digest, request_key)
    browser_confirmation()
    if not isinstance(approval_token, str) or len(approval_token) != 64:
        fail("Invalid approval token", True)
    name = hashlib.sha256(approval_token.encode()).hexdigest()
    # Lock is retained until the request transaction commits or rolls back; result and mutation commit together.
    row = frappe.db.get_value(APPROVAL, name,
                              ["user", "digest", "request_key", "expires_at", "status", "result_json"],
                              as_dict=True, for_update=True)
    if not row or row.user != frappe.session.user or row.digest != digest or row.request_key != request_key:
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
    if (frappe.flags.get("zebra_tool_call") or not request or request.method != "POST"
            or frappe.get_request_header("Authorization")
            or not request.cookies.get("sid") or request.cookies.get("sid") != frappe.session.sid
            or not isinstance(saved, str) or not isinstance(supplied, str)
            or not hmac.compare_digest(saved, supplied)):
        fail("Approval requires a signed-in browser session and CSRF token", True)


@frappe.whitelist(methods=["POST"])
def confirm(proposal_id):
    browser_confirmation()
    if not isinstance(proposal_id, str) or len(proposal_id) != 64:
        fail("Invalid proposal id")
    row = frappe.db.get_value(APPROVAL, proposal_id,
                              ["user", "operation", "arguments_json", "request_id", "digest",
                               "expires_at", "status", "result_json"], as_dict=True, for_update=True)
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


def checked_file(args, target, permission):
    file = frappe.get_doc("File", args["file"], for_update=permission != "read")
    file.check_permission("delete" if permission == "delete" else "read")
    if file.is_folder or not file.attached_to_doctype or not file.attached_to_name:
        fail("Only document attachments are supported", True)
    source = document({"doctype": file.attached_to_doctype, "name": file.attached_to_name,
                       "company": args.get("company")}, "read")
    if permission in {"delete", "download"} and (source.doctype != target.doctype or source.name != target.name):
        fail("Attachment belongs to another document", True)
    return file


def attachment(operation, args, doc):
    if operation == "upload_file":
        filename = args["filename"]
        if PurePath(filename).name != filename or "\\" in filename or PurePath(filename).suffix.lower() not in {
            ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".txt", ".csv", ".xlsx", ".docx", ".pptx", ".zip"
        }:
            fail("Unsupported attachment filename/type")
        try:
            content = base64.b64decode(args["content_base64"], validate=True)
        except (ValueError, TypeError, binascii.Error):
            fail("Attachment content must be base64")
        if not content or len(content) > 512 * 1024:
            fail("Attachments must contain 1 byte to 512 KB")
        # Native File hooks enforce configured extension/size limits, PDF checks and rollback cleanup.
        file = frappe.get_doc({"doctype": "File", "file_name": filename, "content": content,
                               "attached_to_doctype": doc.doctype, "attached_to_name": doc.name,
                               "is_private": 1})
        file.insert()
    elif operation == "attach_file":
        source = checked_file(args, doc, "read")
        file = source.create_attachment_copy(doc.doctype, doc.name)
    else:
        file = checked_file(args, doc, "delete")
        name = file.name
        file.delete()
        return {"removed": True, "file": name}
    return {"name": file.name, "file_name": file.file_name, "url": file.file_url, "is_private": bool(file.is_private)}


def complete_approval(name, operation, args):
    # Reuse Frappe's document-hook transaction guard so native methods cannot commit before the receipt.
    frappe.db._disable_transaction_control += 1
    try:
        result = bounded(write(operation, args))
        frappe.db.set_value(APPROVAL, name, {"status": "Completed", "result_json": canonical(result)})
        return result
    finally:
        frappe.db._disable_transaction_control -= 1
