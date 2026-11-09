"""Discover native capabilities available to the authenticated Frappe user."""

import frappe

LAYOUT_FIELDS = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading"}
# Administration and executable configuration are deliberately outside this adapter.
RESTRICTED = {
    "User",
    "Role",
    "Role Profile",
    "User Permission",
    "DocPerm",
    "Custom DocPerm",
    "DocType",
    "DocField",
    "Custom Field",
    "Property Setter",
    "Server Script",
    "Client Script",
    "Workflow",
    "Workflow State",
    "Workflow Action Master",
    "Report",
    "Print Format",
    "Notification",
    "Webhook",
    "Scheduled Job Type",
    "System Settings",
    "Website Settings",
    "Social Login Key",
    "OAuth Client",
    "OAuth Bearer Token",
    "Connected App",
    "Integration Request",
    "Data Import",
    "Data Export",
    "File",
    "Zebra Business Approval",
    "Zebra Settings",
    "Zebra Conversation",
}


SETTINGS_FIELDS = {
    "System Settings": {
        "language",
        "time_zone",
        "currency",
        "date_format",
        "time_format",
        "number_format",
        "float_precision",
        "currency_precision",
        "first_day_of_the_week",
    }
}


def authenticated():
    if not frappe.session.user or frappe.session.user == "Guest":
        frappe.throw("Sign in to use business capabilities", frappe.PermissionError)


def meta_for(doctype):
    if not isinstance(doctype, str) or not doctype or len(doctype) > 140:
        frappe.throw("Invalid DocType")
    # ponytail: "Zebra " is reserved for this adapter's private coordination
    # records. Their dedicated RPCs enforce owner/company scope independently.
    if doctype.startswith("Zebra "):
        frappe.throw("Agent private records are not business data", frappe.PermissionError)
    meta = frappe.get_meta(doctype)
    if meta.istable or meta.is_virtual or not frappe.has_permission(doctype, "read"):
        frappe.throw("DocType is not available", frappe.PermissionError)
    return meta


def mutable(meta):
    return meta.name not in RESTRICTED and not meta.issingle and not meta.name.startswith("Zebra ")


def permitted_fields(meta, parenttype=None, permission_type="read"):
    allowed = set(
        meta.get_permitted_fieldnames(parenttype=parenttype, permission_type=permission_type)
    )
    # Frappe excludes child Tables from value-field enumeration. Their parent
    # permlevel still governs access; child scalar fields use parent permissions.
    tables = [f for f in meta.fields if f.fieldtype in {"Table", "Table MultiSelect"}]
    if tables:
        levels = set(
            meta.get_permlevel_access(parenttype=parenttype, permission_type=permission_type)
        )
        no_permissions = not meta.get_permissions(parenttype=parenttype)
        allowed.update(
            f.fieldname for f in tables if no_permissions or int(f.permlevel or 0) in levels
        )
    return allowed


def readable_fields(meta, parenttype=None):
    allowed = permitted_fields(meta, parenttype)
    # Never expose credentials or values masked by the installed application.
    return {
        f.fieldname
        for f in meta.fields
        if f.fieldname in allowed
        and f.fieldtype not in LAYOUT_FIELDS | {"Password"}
        and not f.get("mask")
    }


def published_actions(doctype=None):
    """Explicit app hook registry, never an arbitrary RPC/module namespace."""
    actions = frappe.get_hooks("zebra_business_actions") or {}
    from zebra_erpnext.business_actions import available

    result = available(doctype)
    for name, entries in actions.items():
        entry = entries[-1] if isinstance(entries, list) else entries
        if not isinstance(entry, dict) or name in result:
            continue
        # Frappe recursively listifies dictionary hook leaves; list-of-dict entries stay intact.
        entry = {
            key: value[-1] if isinstance(value, list) and value else value
            for key, value in entry.items()
        }
        parameters = entry.get("parameters", {})
        if not isinstance(parameters, dict):
            continue
        entry["parameters"] = {
            key: value[-1] if isinstance(value, list) and value else value
            for key, value in parameters.items()
        }
        if not isinstance(entry.get("doctype"), str) or not isinstance(
            entry.get("permission"), str
        ):
            continue
        if doctype and entry.get("doctype") != doctype:
            continue
        if entry.get("permission") not in {"read", "write", "submit", "cancel"}:
            continue
        if entry.get("doctype") in RESTRICTED:
            continue
        if frappe.has_permission(entry.get("doctype"), entry["permission"]):
            result[name] = entry
    return result


def describe(doctype):
    meta = meta_for(doctype)
    allowed = readable_fields(meta)
    fields = []
    for field in meta.fields:
        if field.fieldname not in allowed:
            continue
        item = {
            "fieldname": field.fieldname,
            "label": field.label,
            "fieldtype": field.fieldtype,
            "required": bool(field.reqd),
            "read_only": bool(field.read_only),
            "options": field.options,
        }
        if field.fieldtype in {"Table", "Table MultiSelect"}:
            child = frappe.get_meta(field.options)
            child_allowed = readable_fields(child, parenttype=doctype)
            item["fields"] = [
                {
                    "fieldname": f.fieldname,
                    "fieldtype": f.fieldtype,
                    "label": f.label,
                    "required": bool(f.reqd),
                    "read_only": bool(f.read_only),
                    "options": f.options,
                }
                for f in child.fields
                if f.fieldname in child_allowed
            ]
        fields.append(item)
    operations = ["get"] if meta.issingle else ["query", "query_page", "aggregate", "get"]
    if not meta.issingle and frappe.has_permission(doctype, "export"):
        operations.append("export")
    if mutable(meta):
        for operation, permission in [
            ("create", "create"),
            ("update", "write"),
            ("delete", "delete"),
        ]:
            if frappe.has_permission(doctype, permission):
                operations.append(operation)
        if meta.is_submittable:
            for operation in ("submit", "cancel", "amend"):
                if frappe.has_permission(doctype, operation):
                    operations.append(operation)
        from frappe.model.workflow import get_workflow_name

        if get_workflow_name(doctype):
            operations.append("workflow_transitions")
            if frappe.has_permission(doctype, "write"):
                operations.append("workflow")
    if doctype in SETTINGS_FIELDS and frappe.has_permission(doctype, "write"):
        operations.append("settings_update")
    if any(entry.get("conversion") for entry in published_actions(doctype).values()):
        operations.append("create_from_action")
    if mutable(meta) and frappe.has_permission(doctype, "write"):
        operations.extend(["upload_file", "attach_file", "remove_file", "comment"])
    if frappe.has_permission(doctype, "print"):
        operations.append("print")
    if frappe.has_permission("File", "read"):
        operations.extend(["files", "download_file"])
    mutation_published = any(
        op
        in {
            "create",
            "update",
            "delete",
            "submit",
            "cancel",
            "amend",
            "workflow",
            "settings_update",
            "create_from_action",
            "comment",
        }
        for op in operations
    )
    return {
        "doctype": doctype,
        "module": meta.module,
        "fields": fields,
        "operations": operations,
        "mutation_availability": {
            "published": mutation_published,
            "reason": None
            if mutation_published
            else (
                "Current role has no published mutation, or this DocType requires a "
                "dedicated administrative/Single "
                "contract"
            ),
        },
        "approval_required_for_writes": True,
        "settings_write_fields": sorted(SETTINGS_FIELDS.get(doctype, set())),
        "actions": [
            {
                "name": name,
                "parameters": e.get("parameters", {}),
                "permission": e["permission"],
                "target_doctype": e.get("target_doctype"),
                "saved": e.get("saved"),
            }
            for name, e in published_actions(doctype).items()
        ],
    }


@frappe.whitelist()
def discover(query=None, doctype=None, start=0, limit=100):
    authenticated()
    if doctype:
        return describe(doctype)
    if query is not None and (not isinstance(query, str) or len(query) > 140):
        frappe.throw("Invalid search query")
    try:
        start, limit = int(start), int(limit)
    except (TypeError, ValueError):
        frappe.throw("Invalid discovery pagination")
    if start < 0 or not 1 <= limit <= 200:
        frappe.throw("Invalid discovery pagination")
    filters = {"istable": 0, "is_virtual": 0}
    if query:
        filters["name"] = ["like", "%" + query + "%"]
    # Metadata inventory is filtered again with the current user's native permissions.
    rows = frappe.get_all(
        "DocType",
        filters=filters,
        fields=["name", "module"],
        order_by="name",
        limit_start=start,
        limit_page_length=limit + 1,
    )
    doctypes_more = len(rows) > limit
    doctypes = [
        row
        for row in rows[:limit]
        if not row.name.startswith("Zebra ") and frappe.has_permission(row.name, "read")
    ]
    from frappe.desk.query_report import get_report_doc

    reports = []
    report_availability = []
    report_filters = {"disabled": 0}
    if query:
        report_filters["name"] = ["like", "%" + query + "%"]
    report_rows = frappe.get_all(
        "Report",
        filters=report_filters,
        fields=["name", "ref_doctype", "report_type"],
        order_by="name",
        limit_start=start,
        limit_page_length=limit + 1,
    )
    reports_more = len(report_rows) > limit
    for row in report_rows[:limit]:
        if str(row.ref_doctype or "").startswith("Zebra "):
            continue
        try:
            get_report_doc(row.name)
        except frappe.PermissionError:
            report_availability.append(
                dict(
                    row,
                    status="role_unavailable",
                    reason="Native report or reference DocType report permission denied",
                )
            )
            continue
        reports.append(row)
        report_availability.append(
            dict(
                row,
                status="mapped_pending_report_qa",
                reason=(
                    "Native report run and stored descriptor supported; report-specific "
                    "acceptance "
                    "pending"
                ),
            )
        )
    return {
        "doctypes": doctypes,
        "reports": reports,
        "doctype_availability": [
            dict(
                row,
                status="native_permission_checked"
                if frappe.has_permission(row.name, "read")
                else "role_unavailable",
                reason=(
                    "Generic lifecycle only; dedicated controller/module acceptance remains pending"
                )
                if frappe.has_permission(row.name, "read")
                else "Native DocType read permission denied",
                mutation_restricted=row.name in RESTRICTED,
            )
            for row in rows[:limit]
            if not row.name.startswith("Zebra ")
        ],
        "report_availability": report_availability,
        "pagination_scope": (
            "Raw metadata rows; denied items remain in availability ledger and advance the cursor"
        ),
        "next_start": start + limit if doctypes_more or reports_more else None,
        "doctypes_has_more": doctypes_more,
        "reports_has_more": reports_more,
        "limits": {"query_rows": 50, "aggregate_rows": 1000, "result_bytes": 200000},
        "coverage": coverage(),
        "restricted_mutation_doctypes": sorted(RESTRICTED),
        "business_actions": list(published_actions()),
        "note": (
            "Metadata permissions are preliminary; document permissions, hooks, "
            "validation and workflow apply at "
            "execution."
        ),
    }


def coverage():
    """Published interface ledger; mapped operations are not module-chain certification."""
    from zebra_erpnext.business_actions import CONVERSIONS

    return {
        "certification": "interface_only_module_chains_pending_qa",
        "published_operations": {
            "query_page": "Permission-filtered page with next_start; at most 50 rows",
            "aggregate": "count/sum/avg/min/max over at most 1000 readable rows; overflow rejected",
            "export": (
                "Native export permission plus readable scalar fields; bounded CSV "
                "page with formula "
                "escaping"
            ),
            "report_describe": (
                "Native report access; stored filters/columns only; dynamic JavaScript "
                "descriptors "
                "pending"
            ),
            "comment": (
                "Plain text native Comment; document write permission, version and "
                "independent "
                "approval"
            ),
        },
        "conversions": [
            {
                "action": name,
                "source": source,
                "target": target,
                "native_entry": path,
                "status": "mapped_pending_module_qa"
                if frappe.has_permission(source, "read")
                and frappe.has_permission(target, "create")
                and frappe.has_permission(target, "read")
                else "role_unavailable",
                "side_effect": "unsaved_draft_or_independently_approved_insert",
                "reason": (
                    "Native mapper validates source state/configuration at execution; not "
                    "a certified business "
                    "chain"
                ),
            }
            for name, (source, target, path) in CONVERSIONS.items()
        ],
        "native_only": [
            {
                "area": "Data Import",
                "status": "pending_implementation",
                "reason": (
                    "Bulk import preview, row validation and approval binding require a "
                    "dedicated contract"
                ),
            },
            {
                "area": "Data Export",
                "status": "partial",
                "reason": (
                    "Bounded scalar CSV export published; native full template/child-table "
                    "export remains "
                    "pending"
                ),
            },
            {
                "area": "Assignment/ToDo collaboration",
                "status": "pending_implementation",
                "reason": (
                    "Assignment recipient authority and notification side effects need a "
                    "reviewed contract"
                ),
            },
            {
                "area": "Single Settings",
                "status": "partial",
                "reason": (
                    "Only System Settings locale/format fields have a dedicated approval contract"
                ),
            },
            {
                "area": "User/Role/Permissions/Workflow definitions",
                "status": "pending_implementation",
                "reason": (
                    "Require dedicated administrator permission and independently approved "
                    "parameter contracts"
                ),
            },
            {
                "area": "Scripts/Credentials/Executable configuration",
                "status": "restricted",
                "reason": (
                    "Native operator workflow required; arbitrary RPC, SQL and executable "
                    "configuration are excluded from this "
                    "adapter"
                ),
            },
            {
                "area": "Stock/Manufacturing/Projects/Assets/Quality/Support controller actions",
                "status": "pending_implementation",
                "reason": (
                    "Generic document lifecycle available; controller actions and module "
                    "chains need source-reviewed mappings and isolated "
                    "QA"
                ),
            },
        ],
        "report_operations": ["report_describe", "report"],
    }
