"""Permission-filtered business queries, reports and exports."""

import csv
import io
from decimal import Decimal, InvalidOperation

import frappe

from zebra_erpnext.capabilities import meta_for, readable_fields


def query(args, extra_row=False, max_rows=50):
    from zebra_erpnext import business

    meta = meta_for(args["doctype"])
    if meta.issingle:
        business.fail("Use get for Single DocTypes")
    allowed = {
        name
        for name in readable_fields(meta)
        if meta.get_field(name).fieldtype not in {"Table", "Table MultiSelect"}
    } | {"name", "owner", "creation", "modified", "modified_by", "docstatus"}
    fields = args.get("fields", ["name", "modified"])
    if (
        not isinstance(fields, list)
        or not fields
        or len(fields) > 30
        or any(
            not isinstance(f, str)
            or f not in allowed
            or meta.get_field(f)
            and meta.get_field(f).fieldtype in {"Table", "Table MultiSelect"}
            for f in fields
        )
    ):
        business.fail("Query fields must be explicit readable scalar field names", True)
    filters = args.get("filters", {})
    if not isinstance(filters, dict) or any(k not in allowed for k in filters):
        business.fail("Filters must use readable field names", True)
    for value in filters.values():
        if isinstance(value, list):
            if (
                len(value) != 2
                or not isinstance(value[0], str)
                or value[0]
                not in {
                    "=",
                    "!=",
                    ">",
                    "<",
                    ">=",
                    "<=",
                    "like",
                    "not like",
                    "in",
                    "not in",
                    "between",
                    "is",
                }
            ):
                business.fail("Unsupported filter operator")
            operator, operand = value
            if operator in {"in", "not in", "between"}:
                if (
                    not isinstance(operand, list)
                    or not operand
                    or len(operand) > 100
                    or any(isinstance(v, dict | list) for v in operand)
                ):
                    business.fail("Invalid filter operand")
                if operator == "between" and len(operand) != 2:
                    business.fail("between requires two filter values")
            elif isinstance(operand, dict | list):
                business.fail("Invalid filter operand")
        elif isinstance(value, dict):
            business.fail("Invalid filter value")
    filters = dict(filters)
    if args.get("company") and meta.name == "Company":
        filters["name"] = args["company"]
    elif args.get("company") and meta.has_field("company"):
        filters["company"] = args["company"]
    limit, start = args.get("limit", 20), args.get("start", 0)
    if (
        type(limit) is not int
        or not 1 <= limit <= max_rows
        or type(start) is not int
        or not 0 <= start <= 10000
    ):
        business.fail("Invalid query pagination")
    order_by = args.get("order_by", "modified desc, name asc")
    if not isinstance(order_by, str) or len(order_by) > 300:
        business.fail("Invalid query ordering")
    terms = [part.strip().split() for part in order_by.split(",")]
    if not 1 <= len(terms) <= 3 or any(
        len(term) not in {1, 2}
        or term[0] not in allowed
        or len(term) == 2
        and term[1].lower() not in {"asc", "desc"}
        for term in terms
    ):
        business.fail("Ordering must use readable scalar field names", True)
    # Native get_list adds match conditions, user permissions and field checks.
    return frappe.get_list(
        meta.name,
        fields=fields,
        filters=filters,
        limit_start=start,
        limit_page_length=limit + int(extra_row),
        order_by=order_by,
    )


def query_page(args):
    from zebra_erpnext import business

    rows = business.query(args, extra_row=True)
    limit, start = args.get("limit", 20), args.get("start", 0)
    return {
        "rows": rows[:limit],
        "has_more": len(rows) > limit,
        "next_start": start + limit if len(rows) > limit else None,
    }


def export(args):
    from zebra_erpnext import business

    if not frappe.has_permission(args["doctype"], "export"):
        business.fail("Export is not permitted", True)
    page = business.query_page(args)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(args["fields"])
    for row in page["rows"]:
        # Spreadsheet applications interpret leading formula markers even in quoted CSV.
        writer.writerow(
            [
                (
                    "'" + value
                    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@"))
                    else value
                )
                for value in (row.get(field) for field in args["fields"])
            ]
        )
    return {
        "content": stream.getvalue(),
        "content_type": "text/csv; charset=utf-8",
        "has_more": page["has_more"],
        "next_start": page["next_start"],
        "row_count": len(page["rows"]),
    }


def aggregate(args):
    from zebra_erpnext import business

    metric, field = args["metric"], args.get("field")
    if not isinstance(metric, str) or metric not in {"count", "sum", "avg", "min", "max"}:
        business.fail("Unsupported aggregate metric")
    meta = meta_for(args["doctype"])
    if metric == "count":
        if field is not None:
            business.fail("count does not accept a field")
    elif (
        not isinstance(field, str)
        or field not in readable_fields(meta)
        or meta.get_field(field).fieldtype
        not in {"Int", "Long Int", "Float", "Currency", "Percent"}
    ):
        business.fail("Aggregate requires a readable numeric field", True)
    # ponytail: scan at most 1000 permission-filtered rows; larger analytics needs a
    # reviewed native report.
    rows = business.query(
        dict(args, fields=[field or "name"], limit=1000), extra_row=True, max_rows=1000
    )
    if len(rows) > 1000:
        business.fail(
            "Aggregate exceeds 1000 accessible rows. Narrow filters or use a native report."
        )
    value = len(rows)
    if metric != "count":
        try:
            values = [Decimal(str(row[field])) for row in rows if row.get(field) is not None]
            if any(not item.is_finite() for item in values):
                business.fail("Aggregate contains non-finite values")
            value = (
                {
                    "sum": lambda: sum(values, Decimal(0)),
                    "avg": lambda: sum(values) / len(values),
                    "min": lambda: min(values),
                    "max": lambda: max(values),
                }[metric]()
                if values
                else None
            )
        except (InvalidOperation, ValueError, TypeError):
            business.fail("Aggregate contains invalid numeric values")
        value = str(value) if value is not None else None
    return {
        "metric": metric,
        "field": field,
        "value": value,
        "row_count": len(rows),
        "complete": True,
    }


def report_describe(name):
    from frappe.desk.query_report import get_report_doc

    report = get_report_doc(name)
    keys = ("fieldname", "label", "fieldtype", "options", "reqd", "default")
    return {
        "name": name,
        "reference_report": report.name,
        "ref_doctype": report.ref_doctype,
        "report_type": report.report_type,
        "prepared_report": bool(report.prepared_report),
        "filters": [{key: row.get(key) for key in keys} for row in report.get("filters") or []],
        "columns": [
            {key: row.get(key) for key in keys if key not in {"reqd", "default"}}
            for row in report.get("columns") or []
        ],
        "descriptor_complete": False,
        "reason": (
            "Native report JavaScript may define additional filters/columns; use "
            "the report page for dynamic descriptors. Scripts and SQL are never "
            "returned."
        ),
    }


def read(operation, args):
    from zebra_erpnext import business

    if operation == "query_page":
        return business.query_page(args)
    if operation == "export":
        return business.export(args)
    if operation == "aggregate":
        return business.aggregate(args)
    if operation == "report_describe":
        return business.report_describe(args["report"])
    if operation == "query":
        return business.query(args)
    if operation == "report":
        from frappe.desk.query_report import get_report_doc, run

        report = get_report_doc(args["report"])
        if report.report_type not in {"Query Report", "Script Report", "Custom Report"}:
            business.fail("Use the ERPNext report page for this report type")
        filters = args.get("filters", {})
        if not isinstance(filters, dict):
            business.fail("Report filters must be an object")
        if args.get("company"):
            filters = dict(filters, company=args["company"])
        return run(args["report"], filters=filters, are_default_filters=False)
    doc = business.document(args)
    if operation == "get":
        return business.serialized(doc)
    if operation == "workflow_transitions":
        from frappe.model.workflow import get_transitions, get_workflow_name

        return get_transitions(doc) if get_workflow_name(doc.doctype) else []
    if operation == "files":
        # File's native match conditions enforce private attachment access.
        return frappe.get_list(
            "File",
            filters={"attached_to_doctype": doc.doctype, "attached_to_name": doc.name},
            fields=["name", "file_name", "file_url", "is_private"],
            limit_page_length=50,
        )
    if operation == "download_file":
        file = business.checked_file(args, doc, "download")
        return {
            "name": file.name,
            "file_name": file.file_name,
            "url": file.file_url,
            "is_private": bool(file.is_private),
        }
    if operation == "print":
        doc.check_permission("print")
        # Return the permission-checked native view URL, without running custom template code here.
        from urllib.parse import urlencode

        return {
            "url": "/printview?"
            + urlencode(
                {"doctype": doc.doctype, "name": doc.name, "format": args.get("format", "Standard")}
            )
        }
