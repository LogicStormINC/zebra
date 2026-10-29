"""Read-only live Frappe16 check, without deploying source or business writes.
Run: python3 tests/test_business_expansion_native.py --ssh ubuntu@HOST --container erpnext-backend-1 --site SITE
Uses the existing SSH authorization. No site configuration or credentials are read.
"""
import argparse
import base64
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--ssh', required=True)
parser.add_argument('--container', required=True)
parser.add_argument('--site', required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
source = {name: base64.b64encode((root / 'zebra_erpnext' / (name + '.py')).read_bytes()).decode()
          for name in ('business_actions', 'capabilities', 'business')}
script = '''import base64, inspect, json, sys, types
import frappe
frappe.init(site=SITE)
frappe.connect()
try:
    frappe.set_user('Administrator')
    for name, source in SOURCES.items():
        full_name = 'zebra_erpnext.' + name
        module = types.ModuleType(full_name)
        sys.modules[full_name] = module
        exec(compile(base64.b64decode(source), full_name, 'exec'), module.__dict__)
    b = sys.modules['zebra_erpnext.business']
    c = sys.modules['zebra_erpnext.capabilities']
    page = b.bounded(b.read('query_page', {'doctype': 'Company', 'fields': ['name'], 'limit': 1}))
    assert page['rows'] and isinstance(page['has_more'], bool)
    inventory = c.discover(limit=200)
    assert len(inventory['doctype_availability']) == 200 and inventory['next_start'] == 200
    assert len(inventory['report_availability']) == 194
    result = b.bounded(b.read('aggregate', {'doctype': 'Company', 'metric': 'count'}))
    assert result['complete'] and result['value'] >= len(page['rows'])
    exported = b.bounded(b.read('export', {'doctype': 'Company', 'fields': ['name'], 'limit': 1}))
    assert exported['row_count'] == 1 and exported['content_type'].startswith('text/csv')
    try:
        b.read('query_page', {'doctype': 'Company', 'fields': ['name'], 'order_by': 'name; drop table'})
    except frappe.PermissionError:
        pass
    else:
        raise AssertionError('Invalid order accepted')
    from frappe.desk.query_report import get_report_doc
    report_count = 0
    for row in frappe.get_all('Report', filters={'disabled': 0}, fields=['name']):
        try:
            get_report_doc(row.name)
            descriptor = b.execute('report_describe', {'report': row.name, 'company': page['rows'][0]['name']}, 'native-report-metadata')
        except frappe.PermissionError:
            continue
        assert 'javascript' not in descriptor and 'query' not in descriptor
        report_count += 1
    assert report_count
    for entry in c.coverage()['conversions']:
        fn = frappe.get_attr(entry['native_entry'])
        frappe.is_whitelisted(fn)
        inspect.signature(fn).bind(*(['Sales Order', 'no-business-write'] if entry['action'].endswith('.make_payment_entry') else ['no-business-write']))
    from frappe.model.document import Document
    inspect.signature(Document.add_comment).bind(object(), 'Comment', text='plain text')
    # An existing low-privilege principal suffices: no QA user or business data is created.
    frappe.set_user('Guest')
    for operation, arguments in [('query_page', {'doctype':'Company'}), ('aggregate', {'doctype':'Company', 'metric':'count'}), ('export', {'doctype':'Company', 'fields':['name']})]:
        try:
            b.read(operation, arguments)
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError(operation + ' allowed Guest Company data')
    print(json.dumps({'native_read_checks':'passed', 'accessible_reports_described':report_count, 'conversion_signatures_checked':len(c.coverage()['conversions']), 'business_writes':0}))
finally:
    frappe.db.rollback()
    frappe.destroy()
'''
script = 'SITE = ' + repr(args.site) + '\nSOURCES = ' + repr(source) + '\n' + script
command = ['docker', 'exec', '-i', '-w', '/home/frappe/frappe-bench/sites', args.container,
           '/home/frappe/frappe-bench/env/bin/python', '-']
import shlex
subprocess.run(['ssh', args.ssh, shlex.join(command)], input=script, text=True, check=True)
