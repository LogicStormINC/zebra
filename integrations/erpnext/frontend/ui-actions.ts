// Browser-side handlers for the published frontend profile revision 2 actions.
// The cloud manifest (frontend_profile.py) is the contract authority: every
// handler validates the expected page context, applies typed inputs through
// native Frappe APIs only, and returns results shaped to the action's schema.
import * as protocol from './protocol.mjs';

type Any = any;
const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

declare global { interface Window { frappe: any; cur_frm: any; cur_list: any; } }

export function installErpUiActions(client: Any, deps: { pageContext: () => { route: string[]; doctype: string | null; name: string | null }; markNavigation: (target: { doctype: string; name: string } | null) => void }) {
  const currentForm = () => (window.cur_frm && window.cur_frm.doc ? window.cur_frm : null);

  function contextPayload() {
    const page = deps.pageContext();
    const form = currentForm();
    return {
      route: page.route,
      doctype: page.doctype || form?.doc?.doctype || '',
      name: page.name || form?.doc?.name || '',
      modified: String(form?.doc?.modified || ''),
      company: String(form?.doc?.company || ''),
      controller_instance: form ? 'cur_frm' : '',
      load_generation: 0,
    };
  }

  function expectPage(expected: Any, strict: boolean) {
    if (!expected || !Array.isArray(expected.route) || !expected.route.length) return contextPayload();
    const current = deps.pageContext().route;
    const matches = JSON.stringify(current.slice(0, expected.route.length)) === JSON.stringify(expected.route);
    // Strict callers (reads and form mutations) fail closed on page drift.
    // Navigation actions tolerate drift: their purpose is to change the page,
    // and models routinely pass the destination instead of the origin.
    if (strict && !matches) throw new Error('当前页面与预期不符；请先读取页面上下文再操作');
    return contextPayload();
  }

  function expectForm(expected: Any) {
    const context = expectPage(expected, true);
    const form = currentForm();
    if (!form) throw new Error('当前页面没有打开的表单');
    if (expected.doctype && form.doc.doctype !== expected.doctype) throw new Error('表单类型与预期不符');
    if (expected.name && form.doc.name !== expected.name) throw new Error('表单单据与预期不符');
    if (expected.modified && String(form.doc.modified) !== String(expected.modified)) throw new Error('单据已变化，请重新确认页面');
    return { context, form };
  }

  async function navigate(route: string[], wait: 'form' | 'list' | 'none' = 'none'): Promise<{ context: Any; opened: boolean; state: 'loaded' | 'pending' }> {
    await window.frappe.set_route(...route);
    const deadline = Date.now() + 4000;
    while (Date.now() < deadline) {
      await sleep(120);
      const page = deps.pageContext();
      const onRoute = JSON.stringify(page.route.slice(0, route.length)) === JSON.stringify(route);
      if (!onRoute) continue;
      if (wait === 'form' && !currentForm()) continue;
      if (wait === 'list' && !window.cur_list) continue;
      return { context: contextPayload(), opened: true, state: 'loaded' };
    }
    const settled = JSON.stringify(deps.pageContext().route.slice(0, route.length)) === JSON.stringify(route);
    return { context: contextPayload(), opened: settled, state: settled ? 'loaded' : 'pending' };
  }

  const scalarOf = (cell: Any): string | number | boolean | null => {
    if (cell.kind === 'text') return String(cell.text ?? '');
    if (cell.kind === 'number') { const value = Number(cell.number); if (!Number.isFinite(value)) throw new Error('数值字段无效'); return value; }
    if (cell.kind === 'boolean') return cell.boolean === true;
    if (cell.kind === 'null') return null;
    throw new Error('字段类型无效');
  };

  client.registry.mount('erpnext.ui.document.open', async (args: Any) => {
    if (typeof args?.doctype !== 'string' || typeof args.name !== 'string' || !args.doctype || !args.name) throw new Error('单据参数无效');
    expectPage(args.expected, false);
    const target = { doctype: args.doctype, name: args.name };
    deps.markNavigation(target);
    try {
      const result = await navigate(['Form', args.doctype, args.name], 'form');
      const page = deps.pageContext();
      if (page.doctype !== target.doctype || page.name !== target.name) throw new Error('单据页面未能打开');
      return result;
    } finally {
      // Authorized navigation must not invalidate its own receipt; advance after.
      setTimeout(() => { deps.markNavigation(null); client.uiRevision.bump(); }, 0);
    }
  });

  client.registry.mount('erpnext.ui.list.open', async (args: Any) => {
    if (typeof args?.doctype !== 'string' || !args.doctype) throw new Error('列表参数无效');
    expectPage(args.expected, false);
    const result = await navigate(['List', args.doctype], 'list');
    const filters = Array.isArray(args.filters) ? args.filters : [];
    if (filters.length && window.cur_list?.filter_area) {
      for (const filter of filters.slice(0, 20)) {
        const value = filter.kind === 'texts' ? filter.texts : filter.kind === 'numbers' ? filter.numbers
          : filter.kind === 'booleans' ? filter.booleans : filter.kind === 'null' ? null : scalarOf(filter);
        try { window.cur_list.filter_area.add_filter(filter.field, filter.operator, value); }
        catch { return { ...result, state: 'pending' as const }; }
      }
    }
    return { ...result, complete: false };
  });

  client.registry.mount('erpnext.ui.report.open', async (args: Any) => {
    if (typeof args?.report !== 'string' || !args.report) throw new Error('报表参数无效');
    expectPage(args.expected, false);
    const result = await navigate(['query-report', args.report]);
    return result;
  });

  client.registry.mount('erpnext.ui.document.new', async (args: Any) => {
    if (typeof args?.doctype !== 'string' || !args.doctype) throw new Error('新建参数无效');
    expectPage(args.expected, false);
    const result = await navigate(['Form', args.doctype, 'new'], 'form');
    return { context: result.context, saved: false };
  });

  client.registry.mount('erpnext.ui.page.read', async (args: Any) => {
    const { context } = { context: expectPage(args?.expected, true) };
    const form = currentForm();
    const cells: Any[] = [];
    if (form) {
      for (const field of (args.fields || []).slice(0, 30)) {
        if (!(field in form.doc)) continue;
        const value = form.doc[field];
        const kind = value === null || value === undefined ? 'null' : typeof value === 'number' ? 'number' : typeof value === 'boolean' ? 'boolean' : 'text';
        cells.push({ row: form.doc.name, table: '', field, kind, ...(kind === 'text' ? { text: String(value) } : kind === 'null' ? {} : { [kind]: value }) });
      }
      return { context, scope: 'form', company: String(form.doc.company || ''), controller_instance: 'cur_frm', load_generation: 0, complete: true, reason: '', columns: [], cells, pages: [] };
    }
    return { context, scope: 'metadata', company: '', controller_instance: '', load_generation: 0, complete: false,
      reason: '当前页面不是已打开的表单；列表与报表数据请使用 erpnext.read。', columns: [], cells: [], pages: [] };
  });

  client.registry.mount('erpnext.ui.form.fill', async (args: Any) => {
    const { form } = expectForm(args?.expected);
    const expectedPage = { route: args.expected.route, doctype: args.expected.doctype, name: args.expected.name };
    const changed: Any[] = [];
    for (const cell of (args.values || []).slice(0, 30)) {
      const field = cell.field;
      const meta = form.get_docfield?.(field);
      if (!meta || meta.read_only || meta.hidden || Number(meta.permlevel || 0) > 0 || ['name', 'doctype', 'owner', 'docstatus'].includes(field)) throw new Error(`字段不可安全填写：${field}`);
      protocol.assertCurrentForm(expectedPage, deps.pageContext(), window.cur_frm);
      await form.set_value(field, scalarOf(cell));
      changed.push({ name: form.doc.name, field });
    }
    return { context: contextPayload(), saved: false, partial: false, changed, created: [] };
  });

  client.registry.mount('erpnext.ui.form.children.patch', async (args: Any) => {
    const { form } = expectForm(args?.expected);
    const field = args.field;
    const meta = form.get_docfield?.(field);
    if (!meta || meta.fieldtype !== 'Table' || !meta.options) throw new Error(`不是子表字段：${field}`);
    if (((args.updates || []).length + (args.append || []).length) > 100) throw new Error('子表修改超过 100 个单元格');
    const changed: Any[] = [], created: Any[] = [];
    const table = form.doc[field] || [];
    for (const update of (args.updates || []).slice(0, 100)) {
      const row = table.find((item: Any) => item.name === update.name);
      if (!row) throw new Error(`子表行不存在：${update.name}`);
      row[update.field] = scalarOf(update);
      changed.push({ name: update.name, field: update.field });
    }
    const grouped = new Map<string, Any>();
    for (const append of (args.append || []).slice(0, 100)) {
      if (!grouped.has(append.row_key)) grouped.set(append.row_key, { row_key: append.row_key, cells: [] });
      grouped.get(append.row_key).cells.push(append);
    }
    for (const entry of grouped.values()) {
      const row = window.frappe.model.add_child(form.doc, meta.options, field);
      for (const cell of entry.cells) row[cell.field] = scalarOf(cell);
      created.push({ row_key: entry.row_key, name: row.name });
    }
    if (changed.length || created.length) form.refresh_field(field);
    return { context: contextPayload(), saved: false, partial: false, changed, created };
  });
}
