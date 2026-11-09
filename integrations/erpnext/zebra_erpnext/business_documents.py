"""Business argument, document and field permission validation."""

import frappe

from zebra_erpnext.capabilities import SETTINGS_FIELDS, meta_for, permitted_fields, readable_fields


def validate(operation, arguments):
    from zebra_erpnext import business

    if operation not in business.SCHEMAS:
        business.fail("Unsupported business operation")
    args = frappe.parse_json(arguments) if isinstance(arguments, str) else arguments
    if not isinstance(args, dict):
        business.fail("arguments must be an object")
    required, allowed = business.SCHEMAS[operation]
    if required - args.keys() or args.keys() - allowed:
        business.fail("Missing or unsupported operation arguments")
    try:
        encoded = business.canonical(args)
    except (ValueError, TypeError):
        business.fail("Arguments must contain finite JSON values")
    if len(encoded.encode()) > (800000 if operation == "upload_file" else 100000):
        business.fail("Arguments exceed the operation size limit")
    for key in (
        "doctype",
        "name",
        "modified",
        "company",
        "report",
        "action",
        "format",
        "file",
        "filename",
    ):
        if key in args and (
            not isinstance(args[key], str) or not args[key] or len(args[key]) > 140
        ):
            business.fail("Invalid " + key)
    if args.get("company") and not frappe.get_list(
        "Company", filters={"name": args["company"]}, fields=["name"], limit_page_length=1
    ):
        business.fail("Company is not accessible", True)
    if operation == "settings_update" and (
        args["doctype"] not in SETTINGS_FIELDS
        or args["name"] != args["doctype"]
        or not isinstance(args["values"], dict)
        or not args["values"]
        or not args["values"].keys() <= SETTINGS_FIELDS[args["doctype"]]
    ):
        business.fail("Only published locale/format settings may be changed", True)
    return args


def check_company(doc, company=None):
    from zebra_erpnext import business

    actual = (
        doc.name
        if doc.doctype == "Company"
        else (doc.get("company") if doc.meta.has_field("company") else None)
    )
    if company and actual and actual != company:
        business.fail("Document is outside the approved company", True)
    if actual and not frappe.get_list(
        "Company", filters={"name": actual}, fields=["name"], limit_page_length=1
    ):
        business.fail("Document company is not accessible", True)


def document(args, permission="read", lock=False):
    from zebra_erpnext import business

    meta_for(args["doctype"])
    doc = frappe.get_doc(args["doctype"], args["name"], for_update=lock)
    doc.check_permission(permission)
    business.check_company(doc, args.get("company"))
    if "modified" in args and str(doc.modified) != args["modified"]:
        business.fail("Document changed. Refresh and request a new approval.")
    return doc


def serialized(doc):
    from zebra_erpnext import business

    doc.check_permission("read")
    doc.apply_fieldlevel_read_permissions()
    return business.clean_document(doc)


def clean_document(doc, parenttype=None):
    from zebra_erpnext import business

    allowed = readable_fields(doc.meta, parenttype=parenttype) | business.SYSTEM_FIELDS
    data = doc.as_dict()
    result = {k: v for k, v in data.items() if k in allowed}
    for field in doc.meta.get_table_fields():
        if field.fieldname in result:
            result[field.fieldname] = [
                business.clean_document(child, doc.doctype)
                for child in doc.get(field.fieldname) or []
            ]
    return result


def checked_values(meta, values, parenttype=None, existing=None):
    from zebra_erpnext import business

    if not isinstance(values, dict) or not values:
        business.fail("values must be a nonempty object")
    allowed = permitted_fields(meta, parenttype, permission_type="write")
    cleaned = {}
    for key, value in values.items():
        field = meta.get_field(key)
        if (
            key in business.SYSTEM_FIELDS | business.FORBIDDEN
            or key.startswith("_")
            or not field
            or key not in allowed
            or field.read_only
            or field.fieldtype == "Password"
        ):
            business.fail("Field is not writable: " + key, True)
        if field.fieldtype in {"Table", "Table MultiSelect"}:
            if not isinstance(value, list) or len(value) > 100:
                business.fail("Child table must contain at most 100 rows")
            child_meta = frappe.get_meta(field.options)
            existing_rows = {row.name: row for row in existing.get(key) or []} if existing else {}
            cleaned[key] = []
            seen = set()
            for row in value:
                if not isinstance(row, dict):
                    business.fail("Child rows must be objects")
                row = dict(row)
                name = row.pop("name", None)
                if name is not None and (not isinstance(name, str) or not name):
                    business.fail("Invalid child row name")
                original = existing_rows.get(name) if name else None
                if name and (
                    not original
                    or name in seen
                    or original.parent != existing.name
                    or original.parenttype != meta.name
                    or original.parentfield != key
                ):
                    business.fail("Child row does not belong to this document and field", True)
                if name:
                    seen.add(name)
                changes = (
                    business.checked_values(
                        child_meta, row, parenttype=meta.name, existing=original
                    )
                    if row
                    else {}
                )
                if not row and not original:
                    business.fail("New child rows must contain values")
                cleaned[key].append(dict(original.as_dict(), **changes) if original else changes)
        elif isinstance(value, dict | list):
            business.fail("Scalar field requires a scalar value: " + key)
        else:
            cleaned[key] = value
    return cleaned
