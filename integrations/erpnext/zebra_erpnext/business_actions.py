"""Reviewed ERPNext conversions. Source only; no caller-supplied module paths or bypass flags."""

# Native functions return drafts. Saving/submitting remains a separate approved operation.
CONVERSIONS = {
    "lead.make_opportunity": (
        "Lead",
        "Opportunity",
        "erpnext.crm.doctype.lead.lead.make_opportunity",
    ),
    "lead.make_quotation": ("Lead", "Quotation", "erpnext.crm.doctype.lead.lead.make_quotation"),
    "opportunity.make_quotation": (
        "Opportunity",
        "Quotation",
        "erpnext.crm.doctype.opportunity.opportunity.make_quotation",
    ),
    "opportunity.make_customer": (
        "Opportunity",
        "Customer",
        "erpnext.crm.doctype.opportunity.opportunity.make_customer",
    ),
    "supplier_quotation.make_purchase_order": (
        "Supplier Quotation",
        "Purchase Order",
        ("erpnext.buying.doctype.supplier_quotation.supplier_quotation.make_purchase_order"),
    ),
    "quotation.make_sales_order": (
        "Quotation",
        "Sales Order",
        "erpnext.selling.doctype.quotation.quotation.make_sales_order",
    ),
    "quotation.make_sales_invoice": (
        "Quotation",
        "Sales Invoice",
        "erpnext.selling.doctype.quotation.quotation.make_sales_invoice",
    ),
    "sales_order.make_sales_invoice": (
        "Sales Order",
        "Sales Invoice",
        ("erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice"),
    ),
    "sales_order.make_delivery_note": (
        "Sales Order",
        "Delivery Note",
        ("erpnext.selling.doctype.sales_order.sales_order.make_delivery_note"),
    ),
    "sales_invoice.make_delivery_note": (
        "Sales Invoice",
        "Delivery Note",
        ("erpnext.accounts.doctype.sales_invoice.sales_invoice.make_delivery_note"),
    ),
    "sales_invoice.make_sales_return": (
        "Sales Invoice",
        "Sales Invoice",
        ("erpnext.accounts.doctype.sales_invoice.sales_invoice.make_sales_return"),
    ),
    "purchase_order.make_purchase_receipt": (
        "Purchase Order",
        "Purchase Receipt",
        ("erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_receipt"),
    ),
    "purchase_order.make_purchase_invoice": (
        "Purchase Order",
        "Purchase Invoice",
        ("erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_invoice"),
    ),
    "purchase_receipt.make_purchase_invoice": (
        "Purchase Receipt",
        "Purchase Invoice",
        ("erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice"),
    ),
    "purchase_receipt.make_purchase_return": (
        "Purchase Receipt",
        "Purchase Receipt",
        ("erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_return"),
    ),
}
for _source in ("Sales Order", "Sales Invoice", "Purchase Order", "Purchase Invoice"):
    CONVERSIONS[_source.lower().replace(" ", "_") + ".make_payment_entry"] = (
        _source,
        "Payment Entry",
        ("erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry"),
    )


def available(doctype=None):
    import frappe

    return {
        name: {
            "doctype": source,
            "target_doctype": target,
            "conversion": path,
            "permission": "read",
            "parameters": {},
            "saved": False,
        }
        for name, (source, target, path) in CONVERSIONS.items()
        if (not doctype or source == doctype)
        and frappe.has_permission(source, "read")
        and frappe.has_permission(target, "create")
        and frappe.has_permission(target, "read")
    }
