"""Read-only live Frappe16 check, without deploying source or business writes. Run: python3
tests/test_business_expansion_native.py --ssh ubuntu@HOST --container erpnext-backend-1
--site SITE Uses the existing SSH authorization. No site configuration or credentials
are read.
"""

import argparse
import base64
import json as json
import shlex
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ssh", required=True)
parser.add_argument("--container", required=True)
parser.add_argument("--site", required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
source = {
    name: base64.b64encode((root / "zebra_erpnext" / (name + ".py")).read_bytes()).decode()
    for name in ("business_actions", "capabilities", "business")
}
script = (
    "import base64, inspect, json, sys, types\nimport frappe\nfrappe.in"
    "it(site=SITE)\nfrappe.connect()\ntry:\n    frappe.set_user('Adminis"
    "trator')\n    for name, source in SOURCES.items():\n        full_n"
    "ame = 'zebra_erpnext.' + name\n        module = types.ModuleType("
    "full_name)\n        sys.modules[full_name] = module\n        exec("
    "compile(base64.b64decode(source), full_name, 'exec'), module.__d"
    "ict__)\n    b = sys.modules['zebra_erpnext.business']\n    c = sys"
    ".modules['zebra_erpnext.capabilities']\n    page = b.bounded(b.re"
    "ad('query_page', {'doctype': 'Company', 'fields': ['name'], 'lim"
    "it': 1}))\n    assert page['rows'] and isinstance(page['has_more'"
    "], bool)\n    inventory = c.discover(limit=200)\n    assert len(in"
    "ventory['doctype_availability']) == 200 and inventory['next_star"
    "t'] == 200\n    assert len(inventory['report_availability']) == 1"
    "94\n    result = b.bounded(b.read('aggregate', {'doctype': 'Compa"
    "ny', 'metric': 'count'}))\n    assert result['complete'] and resu"
    "lt['value'] >= len(page['rows'])\n    exported = b.bounded(b.read"
    "('export', {'doctype': 'Company', 'fields': ['name'], 'limit': 1"
    "}))\n    assert exported['row_count'] == 1 and exported['content_"
    "type'].startswith('text/csv')\n    try:\n        b.read('query_pag"
    "e', {'doctype': 'Company', 'fields': ['name'], 'order_by': 'name"
    "; drop table'})\n    except frappe.PermissionError:\n        pass\n"
    "    else:\n        raise AssertionError('Invalid order accepted')"
    "\n    from frappe.desk.query_report import get_report_doc\n    rep"
    "ort_count = 0\n    for row in frappe.get_all('Report', filters={'"
    "disabled': 0}, fields=['name']):\n        try:\n            get_re"
    "port_doc(row.name)\n            descriptor = b.execute('report_de"
    "scribe', {'report': row.name, 'company': page['rows'][0]['name']"
    "}, 'native-report-metadata')\n        except frappe.PermissionErr"
    "or:\n            continue\n        assert 'javascript' not in desc"
    "riptor and 'query' not in descriptor\n        report_count += 1\n "
    "   assert report_count\n    for entry in c.coverage()['conversion"
    "s']:\n        fn = frappe.get_attr(entry['native_entry'])\n       "
    " frappe.is_whitelisted(fn)\n        inspect.signature(fn).bind(*("
    "['Sales Order', 'no-business-write'] if entry['action'].endswith"
    "('.make_payment_entry') else ['no-business-write']))\n    from fr"
    "appe.model.document import Document\n    inspect.signature(Docume"
    "nt.add_comment).bind(object(), 'Comment', text='plain text')\n   "
    " # An existing low-privilege principal suffices: no QA user or b"
    "usiness data is created.\n    frappe.set_user('Guest')\n    for op"
    "eration, arguments in [('query_page', {'doctype':'Company'}), ('"
    "aggregate', {'doctype':'Company', 'metric':'count'}), ('export',"
    " {'doctype':'Company', 'fields':['name']})]:\n        try:\n      "
    "      b.read(operation, arguments)\n        except frappe.Permiss"
    "ionError:\n            pass\n        else:\n            raise Asser"
    "tionError(operation + ' allowed Guest Company data')\n    print(j"
    "son.dumps({'native_read_checks':'passed', 'accessible_reports_de"
    "scribed':report_count, 'conversion_signatures_checked':len(c.cov"
    "erage()['conversions']), 'business_writes':0}))\nfinally:\n    fra"
    "ppe.db.rollback()\n    frappe.destroy()\n"
)
script = "SITE = " + repr(args.site) + "\nSOURCES = " + repr(source) + "\n" + script
command = [
    "docker",
    "exec",
    "-i",
    "-w",
    "/home/frappe/frappe-bench/sites",
    args.container,
    "/home/frappe/frappe-bench/env/bin/python",
    "-",
]

subprocess.run(["ssh", args.ssh, shlex.join(command)], input=script, text=True, check=True)
