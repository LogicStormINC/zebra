import { ZebraClientRuntime } from '@zebra-agent/client-core';
import { rpcMethod } from './workbench-state.mjs';
import { installErpUiActions } from './ui-actions';

declare global { interface Window { frappe: any; cur_frm: any; __zebraERP?: boolean; } }
export async function api(method: string, args: Record<string, unknown> = {}) {
  const path = rpcMethod(method);
  const response = await fetch(`/api/method/${path}`, {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','Accept':'application/json','X-Frappe-CSRF-Token':window.frappe.csrf_token || ''},body:JSON.stringify(args)});
  if (!response.ok) {
    // Frappe error bodies carry the real server message (e.g. cloud 404 rejections);
    // surface it before falling back to generic status wording.
    let detail = '';
    try { const value = await response.json();
      if (typeof value?.message === 'string' && value.message) detail = value.message;
      else if (typeof value?.exception === 'string') { const parts = value.exception.split(':'); detail = (parts.slice(1).join(':').trim() || parts[0]).slice(0, 200); }
    } catch {}
    throw new Error(detail || (response.status === 403 ? '没有操作权限或登录已过期，请刷新后核对。' : response.status === 409 ? '单据状态已变化，请重新连接核对。' : `ERP 请求未确认（${response.status}），请核对登录状态与任务。`));
  }
  let value: any;
  try { value = await response.json(); } catch { throw new Error('服务器响应未能读取，请重新连接核对结果。'); }
  if (!value || typeof value !== 'object' || value.exc || value.exc_type || !Object.hasOwn(value,'message')) throw new Error('ERP 请求未确认，请核对单据与任务状态。');
  return value.message;
}
export function pageContext() {
  const route = window.frappe.get_route?.() || [];
  return { route, doctype: route[0] === 'Form' ? route[1] : null, name: route[0] === 'Form' ? route[2] : null };
}

export function createHostClient(surface: any, name: string, markNavigation: (target: { doctype: string; name: string } | null) => void) {
  const config = surface.config || surface;
    const client = ZebraClientRuntime.fromConfig({ ...config, baseUrl: location.origin,
      fetchImpl: async (input: any, init: RequestInit = {}) => {
        const url = new URL(String(input), location.origin);
        if (url.origin !== location.origin || !url.pathname.startsWith('/v1/')) throw new Error('无效的客户端代理路径');
        if (init.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
        const response = await api('client_proxy', { conversation: name, path: url.pathname + url.search,
          method: init.method || 'GET', body: init.body || null, client_session: config.sessionCredential,
          client_fence: config.controllerFenceToken });
        return new Response(typeof response.body === 'string' ? response.body : JSON.stringify(response.body ?? response),
          { status: response.status || 200, headers: { 'Content-Type': 'application/json' } });
      } });
    // Full frontend profile revision 2 actions: document.open, list.open,
    // report.open, document.new, page.read, form.fill, form.children.patch.
    installErpUiActions(client, {
      pageContext,
      markNavigation,
    });
  return client;
}
