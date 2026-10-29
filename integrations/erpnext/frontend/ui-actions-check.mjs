// Contract tests for the frontend profile revision 2 browser actions.
// Compiles ui-actions.ts with esbuild, then drives every mounted handler
// against a mocked frappe surface and asserts the published result schemas.
import assert from 'node:assert/strict';
import esbuild from 'esbuild';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const out = join(mkdtempSync(join(tmpdir(), 'ui-actions-')), 'ui-actions.mjs');
writeFileSync(out, esbuild.buildSync({
  entryPoints: [new URL('./ui-actions.ts', import.meta.url).pathname],
  bundle: true, format: 'esm', platform: 'node', write: false,
  external: ['./protocol.mjs'],
}).outputFiles[0].text.replace(/from'\.\/protocol\.mjs'/g, "from './protocol.mjs'"));
// Keep the real protocol guards: resolve them from this directory.
writeFileSync(join(out, '..', 'protocol.mjs'), (await import('node:fs')).readFileSync(new URL('./protocol.mjs', import.meta.url), 'utf8'));
const { installErpUiActions } = await import(out);

const mounts = {};
const client = { registry: { mount: (name, handler) => { mounts[name] = handler; } }, uiRevision: { bump() {} } };

let route = ['desk', 'setup', 'home'];
let formDoc = null;
const setValues = [];
const refreshed = [];
global.window = {
  frappe: {
    set_route: async (...next) => { route = next; if (next[0] !== 'Form' || next[2] !== 'new') formDoc = next[0] === 'Form' ? { doctype: next[1], name: next[2] } : null; else formDoc = { doctype: next[1], name: 'new-doc', modified: '' }; },
    get_meta: () => null,
    model: { add_child: (doc, doctype, field) => { const row = { name: `new-row-${(doc[field] ||= []).length + 1}` }; doc[field].push(row); return row; } },
  },
  get cur_frm() { return formDoc && formDoc.frm ? formDoc.frm : null; },
  get cur_list() { return null; },
};
const pageContext = () => ({ route, doctype: route[0] === 'Form' ? route[1] : null, name: route[0] === 'Form' ? route[2] : null });
function openForm() {
  formDoc = { doctype: 'Production Plan', name: 'PP-1', docstatus: 0, modified: '2026-10-29T10:00:00.000000', company: '天辰', items: [{ name: 'ROW-A', planned_qty: 1 }, { name: 'ROW-B', planned_qty: 2 }], frm: null };
  formDoc.frm = {
    doc: formDoc,
    get_docfield: field => ({ items: { fieldtype: 'Table', options: 'Production Plan Item' }, planned_start_date: {}, custom_note: {} }[field] || null),
    set_value: async (field, value) => { setValues.push([field, value]); formDoc[field] = value; },
    refresh_field: field => refreshed.push(field),
  };
  route = ['Form', 'Production Plan', 'PP-1'];
}
const expected = { route: ['Form', 'Production Plan', 'PP-1'], doctype: 'Production Plan', name: 'PP-1', modified: '2026-10-29T10:00:00.000000' };

installErpUiActions(client, { pageContext, markNavigation() {} });
assert.equal(Object.keys(mounts).length, 7, 'all revision 2 actions are mounted');

// document.open: navigation tolerates drift (models pass the destination);
// valid navigation settles loaded.
const opened = await mounts['erpnext.ui.document.open']({ doctype: 'Sales Order', name: 'SO-1', expected: { route: ['Form', 'Other'] } });
assert.equal(opened.opened, true); assert.equal(opened.state, 'loaded');
assert.deepEqual(opened.context.route, ['Form', 'Sales Order', 'SO-1']);

// list.open: routes to the native list and reports incomplete list data.
route = ['Form', 'Production Plan', 'PP-1']; formDoc = null;
const list = await mounts['erpnext.ui.list.open']({ doctype: 'Item', expected: { route: ['Form', 'Production Plan', 'PP-1'] } });
assert.deepEqual(route, ['List', 'Item']); assert.equal(list.complete, false);

// report.open routes to query-report.
const report = await mounts['erpnext.ui.report.open']({ report: 'Accounts Receivable', expected: { route: ['List', 'Item'] } });
assert.deepEqual(route, ['query-report', 'Accounts Receivable']); assert.equal(report.state, 'loaded');

// document.new opens a new draft form and never claims saved.
route = ['query-report', 'Accounts Receivable']; formDoc = null;
const draft = await mounts['erpnext.ui.document.new']({ doctype: 'Sales Order', expected: { route: ['query-report', 'Accounts Receivable'] } });
assert.equal(draft.saved, false); assert.deepEqual(route, ['Form', 'Sales Order', 'new']);

// page.read on a form returns typed cells for existing fields; off-form it is honest metadata.
openForm();
const read = await mounts['erpnext.ui.page.read']({ expected: { route: ['Form', 'Production Plan', 'PP-1'] }, fields: ['company', 'items'] });
assert.equal(read.scope, 'form'); assert.equal(read.complete, true);
const company = read.cells.find(cell => cell.field === 'company');
assert.equal(company.kind, 'text'); assert.equal(company.text, '天辰');
assert.ok(!read.cells.some(cell => cell.field === 'not_a_field'), 'absent fields are not fabricated');
route = ['List', 'Item']; formDoc = null;
const meta = await mounts['erpnext.ui.page.read']({ expected: { route: ['List', 'Item'] } });
assert.equal(meta.scope, 'metadata'); assert.equal(meta.complete, false);

// form.fill: typed cells only, readonly/system fields rejected, never saved.
openForm();
await assert.rejects(() => mounts['erpnext.ui.form.fill']({ expected, values: [{ field: 'docstatus', kind: 'number', number: 1 }] }), /不可安全填写/);
const filled = await mounts['erpnext.ui.form.fill']({ expected, values: [{ field: 'custom_note', kind: 'text', text: '备注' }, { field: 'planned_start_date', kind: 'null' }] });
assert.equal(filled.saved, false); assert.deepEqual(filled.changed.map(row => row.field), ['custom_note', 'planned_start_date']);
assert.deepEqual(setValues.at(-2), ['custom_note', '备注']);

// children.patch: cell updates mutate rows; append items group by row_key; never saved.
const patched = await mounts['erpnext.ui.form.children.patch']({ expected: { ...expected, route: ['Form', 'Production Plan', 'PP-1'] }, field: 'items',
  updates: [{ name: 'ROW-A', field: 'planned_qty', kind: 'number', number: 5 }],
  append: [
    { row_key: 'r1', field: 'item_code', kind: 'text', text: 'FG-X' },
    { row_key: 'r1', field: 'planned_qty', kind: 'number', number: 3 },
    { row_key: 'r2', field: 'item_code', kind: 'text', text: 'FG-Y' },
  ] });
assert.equal(patched.saved, false);
assert.equal(formDoc.items.find(row => row.name === 'ROW-A').planned_qty, 5);
assert.equal(formDoc.items.length, 4, 'two appended rows for two row_keys');
const appendedX = formDoc.items[2];
assert.equal(appendedX.item_code, 'FG-X'); assert.equal(appendedX.planned_qty, 3);
assert.deepEqual(patched.created.map(row => row.row_key), ['r1', 'r2']);
assert.ok(refreshed.includes('items'));
await assert.rejects(() => mounts['erpnext.ui.form.children.patch']({ expected, field: 'items',
  updates: Array.from({ length: 60 }, (_, i) => ({ name: 'ROW-A', field: 'planned_qty', kind: 'number', number: i })),
  append: Array.from({ length: 60 }, (_, i) => ({ row_key: 'r', field: 'planned_qty', kind: 'number', number: i })) }), /100/);

console.log('PASS frontend profile revision 2 actions: expected-page guards, typed cells, list/report/new navigation, page.read shapes and child patch grouping');
