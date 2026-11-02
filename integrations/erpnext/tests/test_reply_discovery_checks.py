"""python3 tests/test_reply_discovery_checks.py; no Frappe/model/network."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zebra_erpnext.discovery_view import preview

value = {
    "doctypes": [{"name": "Doc " + str(i), "module": "Manufacturing"} for i in range(100)],
    "reports": [
        {"name": "Report " + str(i), "ref_doctype": "Doc " + str(i), "report_type": "Query Report"}
        for i in range(100)
    ],
    "doctype_availability": [
        {
            "name": "Doc " + str(i),
            "status": "native_permission_checked",
            "reason": "metadata only " * 40,
        }
        for i in range(100)
    ],
    "coverage": {"all_details": "keep original " * 4000},
    "limits": {"query_rows": 50},
    "next_start": 100,
    "doctypes_has_more": True,
    "reports_has_more": True,
}
small = preview(value)
p = json.loads(small)
assert (
    len(small.encode()) <= 8000
    and p["metadata_only"] is True
    and p["document_permissions_checked"] is False
)
assert p["next_start"] == 100 and p["doctypes_has_more"] is True
assert (
    all(d in value["doctypes"] for d in p["doctypes"]) and p["total_in_response"]["doctypes"] == 100
)
assert len(small) < len(json.dumps(value)) / 10
assert preview({"doctype": "one", "fields": [{"fieldname": "name"}]}) is None, (
    "specific schema details must remain readable"
)
assert value["coverage"]["all_details"].startswith("keep original"), "do not mutate source evidence"
print("PASS bounded exact-row discovery view, honest metadata coverage and unchanged full evidence")
