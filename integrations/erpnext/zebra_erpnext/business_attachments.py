"""Document-bound file permission checks and attachment operations."""

import base64
import binascii
from pathlib import PurePath

import frappe


def checked_file(args, target, permission):
    from zebra_erpnext import business

    file = frappe.get_doc("File", args["file"], for_update=permission != "read")
    file.check_permission("delete" if permission == "delete" else "read")
    if file.is_folder or not file.attached_to_doctype or not file.attached_to_name:
        business.fail("Only document attachments are supported", True)
    source = business.document(
        {
            "doctype": file.attached_to_doctype,
            "name": file.attached_to_name,
            "company": args.get("company"),
        },
        "read",
    )
    if permission in {"delete", "download"} and (
        source.doctype != target.doctype or source.name != target.name
    ):
        business.fail("Attachment belongs to another document", True)
    return file


def attachment(operation, args, doc):
    from zebra_erpnext import business

    if operation == "upload_file":
        filename = args["filename"]
        if (
            PurePath(filename).name != filename
            or "\\" in filename
            or PurePath(filename).suffix.lower()
            not in {
                ".pdf",
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
                ".gif",
                ".txt",
                ".csv",
                ".xlsx",
                ".docx",
                ".pptx",
                ".zip",
            }
        ):
            business.fail("Unsupported attachment filename/type")
        try:
            content = base64.b64decode(args["content_base64"], validate=True)
        except (ValueError, TypeError, binascii.Error):
            business.fail("Attachment content must be base64")
        if not content or len(content) > 512 * 1024:
            business.fail("Attachments must contain 1 byte to 512 KB")
        # Native File hooks enforce configured extension/size limits, PDF checks and
        # rollback cleanup.
        file = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": filename,
                "content": content,
                "attached_to_doctype": doc.doctype,
                "attached_to_name": doc.name,
                "is_private": 1,
            }
        )
        file.insert()
    elif operation == "attach_file":
        source = business.checked_file(args, doc, "read")
        file = source.create_attachment_copy(doc.doctype, doc.name)
    else:
        file = business.checked_file(args, doc, "delete")
        name = file.name
        file.delete()
        return {"removed": True, "file": name}
    return {
        "name": file.name,
        "file_name": file.file_name,
        "url": file.file_url,
        "is_private": bool(file.is_private),
    }
