"""Small metadata index; the Host response retains full evidence after this prefix."""

import json


def preview(result):
    if not isinstance(result, dict) or "doctypes" not in result or "reports" not in result:
        return None
    doctypes = result["doctypes"]
    reports = result["reports"]
    view = {
        key: result[key]
        for key in (
            "next_start",
            "doctypes_has_more",
            "reports_has_more",
            "pagination_scope",
            "limits",
        )
        if key in result
    }
    view.update(
        metadata_only=True,
        document_permissions_checked=False,
        total_in_response={"doctypes": len(doctypes), "reports": len(reports)},
        doctypes=list(doctypes),
        reports=list(reports),
    )

    def encode():
        return json.dumps(view, ensure_ascii=False, separators=(",", ":"))

    while len(encode().encode()) > 8000 and (view["doctypes"] or view["reports"]):
        key = "reports" if len(view["reports"]) >= len(view["doctypes"]) else "doctypes"
        view[key].pop()
    view["index_incomplete"] = len(view["doctypes"]) < len(doctypes) or len(view["reports"]) < len(
        reports
    )
    view["details"] = (
        "Full original metadata is retained after this index. Metadata access is "
        "not proof of access to every business document."
    )
    while len(encode().encode()) > 8000 and (view["doctypes"] or view["reports"]):
        key = "reports" if len(view["reports"]) >= len(view["doctypes"]) else "doctypes"
        view[key].pop()
        view["index_incomplete"] = True
    return encode()
