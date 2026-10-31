"""Explicit, disposable HTTP acceptance against an installed app (stdlib only).

ZEBRA_QA_PASSWORD=... python3 tests/test_business_frappe_acceptance.py \
  --url https://erp.example --user Administrator --allow-disposable-writes

Uses normal session login, native CSRF and browser confirmation. Never touches an
existing business document; only a fresh UUID-marked ToDo and its private file.
TLS verification remains enabled. Trust the deployed CA in the Python trust store.
"""

import argparse
import base64
import http.cookiejar
import json
import os
import re
import urllib.error
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--allow-disposable-writes", action="store_true")
    parser.add_argument(
        "--lifecycle",
        action="store_true",
        help="Also test a disposable non-stock Item and Material Request lifecycle",
    )
    args = parser.parse_args()
    if not args.allow_disposable_writes:
        parser.error(
            "This check creates its own disposable fixture; pass --allow-disp"
            "osable-writes explicitly"
        )
    password = os.environ.get("ZEBRA_QA_PASSWORD")
    if not password:
        parser.error("Set ZEBRA_QA_PASSWORD in the environment")
    base = args.url.rstrip("/")
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    csrf = None

    def request(path, data=None):
        headers = {"Accept": "application/json"}
        if csrf:
            headers["X-Frappe-CSRF-Token"] = csrf
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode()
        with opener.open(
            urllib.request.Request(base + path, data=body, headers=headers), timeout=60
        ) as response:
            return response.read()

    def rpc(method, data):
        try:
            response = json.loads(request("/api/method/" + method, data))
        except urllib.error.HTTPError as error:
            problem = json.loads(error.read())
            raise RuntimeError(
                f"{method}: HTTP {error.code}: {problem.get('exception', 'request rejected')}"
            ) from None
        if response.get("exc"):
            raise RuntimeError("Frappe rejected " + method)
        return response["message"]

    rpc("login", {"usr": args.user, "pwd": password})
    desk = request("/app").decode()
    match = re.search(r'frappe\.csrf_token\s*=\s*[\'"]([^\'"]+)', desk)
    if not match:
        raise RuntimeError("Could not obtain the authenticated Desk CSRF token")
    csrf = match.group(1)
    bootstrap = rpc("zebra_erpnext.api.bootstrap", {})
    companies = bootstrap["companies"]
    if not companies:
        raise RuntimeError("QA user needs an accessible Company")
    company = companies[0]
    marker = "ZEBRA-QA-" + uuid.uuid4().hex
    fixture = None
    tests = []

    def execute(operation, arguments, request_id=None):
        arguments = dict(arguments, company=company)
        request_id = request_id or marker + ":" + uuid.uuid4().hex
        call = {"operation": operation, "arguments": arguments, "request_id": request_id}
        proposal = rpc("zebra_erpnext.business.execute", call)
        if not isinstance(proposal, dict) or not proposal.get("approval_required"):
            return proposal
        assert proposal["operation"] == operation and proposal["arguments"] == arguments
        result = rpc("zebra_erpnext.business.confirm", {"proposal_id": proposal["proposal_id"]})
        assert (
            rpc("zebra_erpnext.business.confirm", {"proposal_id": proposal["proposal_id"]})
            == result
        )
        assert rpc("zebra_erpnext.business.execute", call) == result
        return result

    def current():
        return execute("get", {"doctype": "ToDo", "name": fixture})

    def identity():
        doc = current()
        assert marker in doc["description"], (
            "Fixture ownership marker disappeared; refusing modification"
        )
        return {"doctype": "ToDo", "name": fixture, "modified": doc["modified"]}

    try:
        created = execute("create", {"doctype": "ToDo", "values": {"description": marker}})
        fixture = created["name"]
        assert marker in current()["description"]
        tests.append("create/read/approval/replay")
        updated = execute("update", dict(identity(), values={"description": marker + " updated"}))
        assert "updated" in updated["description"]
        tests.append("update/revision")
        content = (marker + " private attachment").encode()
        uploaded = execute(
            "upload_file",
            dict(
                identity(),
                filename=marker + ".txt",
                content_base64=base64.b64encode(content).decode(),
            ),
        )
        assert uploaded["is_private"]
        attachment = execute(
            "download_file", {"doctype": "ToDo", "name": fixture, "file": uploaded["name"]}
        )
        assert request(attachment["url"]) == content
        tests.append("private upload/authorized download")
        execute("remove_file", dict(identity(), file=uploaded["name"]))
        assert not any(
            row["name"] == uploaded["name"]
            for row in execute("files", {"doctype": "ToDo", "name": fixture})
        )
        tests.append("attachment removal")
    finally:
        if fixture:
            execute("delete", identity())
            tests.append("fixture deletion")
    if args.lifecycle:
        import datetime

        item = material = amended = None

        def row_identity(doctype, name):
            doc = execute("get", {"doctype": doctype, "name": name})
            return {"doctype": doctype, "name": name, "modified": doc["modified"]}

        try:
            groups = execute(
                "query",
                {
                    "doctype": "Item Group",
                    "fields": ["name"],
                    "filters": {"is_group": 0},
                    "limit": 1,
                },
            )
            warehouses = execute(
                "query",
                {
                    "doctype": "Warehouse",
                    "fields": ["name"],
                    "filters": {"is_group": 0},
                    "limit": 1,
                },
            )
            item = execute(
                "create",
                {
                    "doctype": "Item",
                    "values": {
                        "item_code": marker,
                        "item_name": marker,
                        "item_group": groups[0]["name"],
                        "stock_uom": "Nos",
                        "is_stock_item": 0,
                    },
                },
            )["name"]
            material = execute(
                "create",
                {
                    "doctype": "Material Request",
                    "values": {
                        "company": company,
                        "material_request_type": "Purchase",
                        "schedule_date": str(datetime.date.today() + datetime.timedelta(days=1)),
                        "items": [
                            {"item_code": item, "qty": 1, "warehouse": warehouses[0]["name"]}
                        ],
                    },
                },
            )["name"]
            assert execute("submit", row_identity("Material Request", material))["docstatus"] == 1
            assert execute("cancel", row_identity("Material Request", material))["docstatus"] == 2
            amended_doc = execute("amend", row_identity("Material Request", material))
            amended = amended_doc["name"]
            assert amended_doc["docstatus"] == 0 and amended_doc["amended_from"] == material
            tests.append(
                "native Material Request create/submit/cancel/amend with no stock movement"
            )
        finally:
            for dt, name in [
                ("Material Request", amended),
                ("Material Request", material),
                ("Item", item),
            ]:
                if name:
                    doc = execute("get", {"doctype": dt, "name": name})
                    if doc["docstatus"] == 1:
                        execute("cancel", row_identity(dt, name))
                    execute("delete", row_identity(dt, name))
            tests.append("native lifecycle fixtures deleted")
    print(
        json.dumps(
            {"passed": tests, "fixture_marker": marker, "fixture_deleted": bool(fixture)},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
