import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AgentChat, AgentComposer, AgentAssetPreview, AgentRunStatus } from '@zebra-agent/react';
import { ZebraClientRuntime } from '@zebra-agent/client-core';
import '@zebra-agent/react/styles.css';
import './components/tokens.css';
import './style.css';
import { gsap, Flip, motionAllowed, installAgentMotion, animateAgentDialog } from './motion';
import { Resources, ResourceFiles } from './resources';
import { Answer } from './answer';
import { Approvals } from './approvals';
import { isActive, isCurrentView, rpcMethod, safeError, confirmationReceipt } from './workbench-state.mjs';
import { sseParser, reduceEvent, assertCurrentForm, attachmentInfo, validateAttachmentBatch, acceptedFileTypes, usageMetrics, runStatus, contextualSuggestions, submissionIdentity } from './protocol.mjs';
// Presentational shells live in ./components and stay host-agnostic (no frappe, no RPC):
// they are the seed of the extractable zebra agent UI package.
import { LauncherPill } from './components/LauncherPill';
import { CopilotDrawer } from './components/CopilotDrawer';
import { WorkbenchShell } from './components/WorkbenchShell';
import { SessionSidebar } from './components/SessionSidebar';
import { WorkbenchHeader } from './components/WorkbenchHeader';
import { ErpStatusBanner } from './components/ErpStatusBanner';
import { Welcome } from './components/Welcome';
import { ComposerDock } from './components/ComposerDock';
import { SettingsPanel } from './components/SettingsPanel';
import { installErpUiActions } from './ui-actions';

declare global { interface Window { frappe: any; cur_frm: any; __zebraERP?: boolean; } }
async function api(method: string, args: Record<string, unknown> = {}) {
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
function pageContext() {
  const route = window.frappe.get_route?.() || [];
  return { route, doctype: route[0] === 'Form' ? route[1] : null, name: route[0] === 'Form' ? route[2] : null };
}
const noop = () => {};
const maintenanceMessage = 'Agent 正在维护，暂时暂停新提交；历史记录仍可查看';
const initial = { messages: [], activities: [], status: 'idle' };


function Panel() {
  const [open, setOpen] = useState(false), [fullscreen, setFullscreen] = useState(false);
  const [present, setPresent] = useState(false);
  const layout = useRef<any>(null), viewEpoch = useRef(0), sendGate = useRef(false);
  const [openedArtifact, setOpenedArtifact] = useState('');
  const [search, setSearch] = useState(''), [drawer, setDrawer] = useState('');
  const [receipt, setReceipt] = useState<any>(null), [stopping, setStopping] = useState(false);
  const confirmationGate = useRef(new Set<string>()), stopGate = useRef<any>(null), drawerFocus = useRef<HTMLElement | null>(null), sidebarFocus = useRef<HTMLElement | null>(null);
  const drafts = useRef(new Map<string, any>()), textRef = useRef('');
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 700), [managing, setManaging] = useState(false);
  const [boot, setBoot] = useState<any>(null), [conversations, setConversations] = useState<any[]>([]);
  const [selected, setSelected] = useState(''), [company, setCompany] = useState('');
  const [state, setState] = useState<any>(initial), [text, setText] = useState('');
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [approvals, setApprovals] = useState<any[]>([]);
  const [sending, setSending] = useState(false), [confirming, setConfirming] = useState('');
  const [model, setModel] = useState('deepseek-v4-flash-executor-v1'), [reasoning, setReasoning] = useState('high');
  const [savingSettings, setSavingSettings] = useState(false), [loadingSettings, setLoadingSettings] = useState(false);
  const [catalog, setCatalog] = useState<any>(null), [usage, setUsage] = useState<any>(null), [artifacts, setArtifacts] = useState<any>(null);
  const [attachments, setAttachments] = useState<any[]>([]), [readingFiles, setReadingFiles] = useState(false), [preview, setPreview] = useState('');
  const filesRef = useRef<any[]>([]), draftEpoch = useRef(0), draftUrls = useRef(new Set<string>());
  const [page, setPage] = useState(pageContext);
  const activeConversation = useRef(''), stream = useRef<AbortController | null>(null), runtime = useRef<ZebraClientRuntime | null>(null);
  const revision = useRef(0), cursor = useRef(''), reconnect = useRef<ReturnType<typeof setTimeout> | null>(null);
  const navigationTarget = useRef<{ doctype: string; name: string } | null>(null);
  const pending = useRef<{ conversation: string; message: string; request_id: string; model_profile: string; reasoning_effort: string; attachments: any[]; attachment_key: string; context: string; synthetic: boolean } | null>(null);
  function changeText(value: string | ((previous: string) => string)) {
    const next = typeof value === 'function' ? value(textRef.current) : value;
    textRef.current = next; setText(next);
  }
  function fail(error: unknown) { setError(safeError(error)); }
  function openDrawer(kind: string) { drawerFocus.current = document.activeElement as HTMLElement; setDrawer(kind); }
  function closeDrawer() { setDrawer(''); requestAnimationFrame(() => drawerFocus.current?.isConnected && drawerFocus.current.focus()); }
  async function refreshBootstrap() { const value = await api('bootstrap'); setBoot(value); return value; }
  function changeFullscreen(value: boolean) {
    if (!open) return;
    const panel = document.querySelector('#zebra-erpnext-root .ze-panel');
    if (panel && motionAllowed()) {
      Flip.killFlipsOf(panel, true); gsap.killTweensOf(panel); gsap.set(panel, { clearProps: 'transform,opacity' });
      layout.current = Flip.getState(panel);
    }
    setFullscreen(value);
  }
  function changeSidebar(value: boolean) {
    if (value) sidebarFocus.current = document.activeElement as HTMLElement;
    const sidebar = document.querySelector('#zebra-erpnext-root .ze-sidebar');
    const apply = () => {
      const main = document.querySelector('#zebra-erpnext-root .ze-main');
      if (main && motionAllowed()) layout.current = Flip.getState(main);
      setSidebarOpen(value);
      if (!value) requestAnimationFrame(() => sidebarFocus.current?.isConnected && sidebarFocus.current.focus());
    };
    if (!value && sidebar && motionAllowed()) gsap.to(sidebar, { x: -18, opacity: 0, duration: .15, overwrite: true, onComplete: apply });
    else apply();
  }
  useEffect(() => installAgentMotion(document.getElementById('zebra-erpnext-root')!), []);
  useLayoutEffect(() => {
    if (open && !present) { setPresent(true); return; }
    if (!present) return;
    const panel = document.querySelector('#zebra-erpnext-root .ze-panel');
    if (!panel) return;
    if (!open) Flip.killFlipsOf([panel, ...panel.querySelectorAll('.ze-main')], true);
    if (!motionAllowed()) { if (!open) setPresent(false); return; }
    const tween = open
      ? gsap.fromTo(panel, { opacity: 0, y: 16, scale: .985 }, { opacity: 1, y: 0, scale: 1, duration: .26, ease: 'power2.out', clearProps: 'transform,opacity', overwrite: true })
      : gsap.to(panel, { opacity: 0, y: 10, scale: .99, duration: .16, ease: 'power2.in', overwrite: true, onComplete: () => setPresent(false) });
    return () => { tween.kill(); };
  }, [open, present]);
  useLayoutEffect(() => {
    if (!layout.current) return;
    if (motionAllowed()) Flip.from(layout.current, { duration: .3, ease: 'power2.out', scale: true });
    layout.current = null;
  }, [fullscreen, sidebarOpen]);
  function releaseDraftUrl(url: string) { if (draftUrls.current.delete(url)) URL.revokeObjectURL(url); }
  function clearDraft() {
    draftEpoch.current += 1;
    for (const item of filesRef.current) releaseDraftUrl(item.url);
    drafts.current.delete(activeConversation.current);
    filesRef.current = []; setAttachments([]); setPreview(''); changeText(''); setReadingFiles(false); pending.current = null;
  }
  async function refreshResources(name: string) {
    const epoch = viewEpoch.current;
    const values = await Promise.allSettled([api('capability_catalog', name ? { conversation: name } : {}), ...(name ? [api('task_usage', { conversation: name }), api('task_artifacts', { conversation: name })] : [])]);
    if (activeConversation.current !== name || epoch !== viewEpoch.current) return;
    if (values[0].status === 'fulfilled') setCatalog(values[0].value); else fail(values[0].reason);
    if (values[1]?.status === 'fulfilled') setUsage(values[1].value);
    if (values[2]?.status === 'fulfilled') setArtifacts(values[2].value);
  }
  async function chooseFiles(list: FileList | null) {
    if (!list?.length || isActive(state.status) || readingFiles || sending || !catalog?.private_uploads) return;
    const epoch = draftEpoch.current, current = filesRef.current, chosen = Array.from(list);
    const added: any[] = [];
    setReadingFiles(true); setError('');
    try {
      validateAttachmentBatch([...current.map(item => item.file), ...chosen], model);
      for (const file of chosen) {
        if (draftEpoch.current !== epoch) return;
        const info = attachmentInfo(file, model), url = URL.createObjectURL(file);
        draftUrls.current.add(url);
        const item = { id: crypto.randomUUID(), name: file.name, isImage: info.kind === 'image', file, url, wire: null }; added.push(item);
        if (item.isImage) {
          const image = new Image(); image.src = url; await image.decode();
          if (draftEpoch.current !== epoch) return;
          if (image.naturalWidth > 8192 || image.naturalHeight > 8192 || image.naturalWidth * image.naturalHeight > 36000000) throw new Error('图片超过 8192 像素边长或 3600 万像素限制');
        }
        const bytes = new Uint8Array(await file.arrayBuffer());
        if (draftEpoch.current !== epoch) return;
        let binary = ''; for (let at = 0; at < bytes.length; at += 8192) binary += String.fromCharCode(...bytes.subarray(at, at + 8192));
        item.wire = { file_name: file.name, media_type: info.mime, content_base64: btoa(binary) };
      }
      if (draftEpoch.current !== epoch) { added.forEach(item => releaseDraftUrl(item.url)); return; }
      filesRef.current = [...current, ...added]; setAttachments(filesRef.current);
      changeText(value => value || '请阅读附件并说明内容。');
    } catch (error) { added.forEach(item => releaseDraftUrl(item.url)); if (draftEpoch.current === epoch) fail(error); }
    finally { if (draftEpoch.current === epoch) setReadingFiles(false); }
  }
  function removeAttachment(id: string) {
    const item = filesRef.current.find(item => item.id === id); if (item) releaseDraftUrl(item.url);
    filesRef.current = filesRef.current.filter(item => item.id !== id); setAttachments(filesRef.current); if (preview === id) setPreview('');
  }
  async function refreshApprovals(name: string) {
    const epoch = viewEpoch.current;
    try {
      const list = await api('approvals', { conversation: name });
      if (activeConversation.current === name && epoch === viewEpoch.current) setApprovals(list || []);
    } catch (error) { if (activeConversation.current === name && epoch === viewEpoch.current) fail(error); }
  }
  useEffect(() => {
    void refreshResources('');
    refreshBootstrap().then(value => { setModel(value.model_profile); setReasoning(value.reasoning_effort); setCompany(value.company || ''); return api('conversations'); }).then(rows => { setConversations(rows); const name = sessionStorage.getItem(`zebra-erpnext:selected:${window.frappe.session.user}`); if (rows.some((row: any) => row.name === name)) void select(name!); }).catch(fail);
    const timer = setInterval(() => {
      const current = pageContext();
      setPage(previous => {
        if (JSON.stringify(previous) !== JSON.stringify(current)) {
          revision.current += 1;
          const expected = navigationTarget.current;
          if (!expected || current.doctype !== expected.doctype || current.name !== expected.name) runtime.current?.uiRevision.bump();
          return current;
        }
        return previous;
      });
    }, 300);
    return () => { draftEpoch.current += 1; for (const url of draftUrls.current) URL.revokeObjectURL(url); draftUrls.current.clear(); clearInterval(timer); stream.current?.abort(); runtime.current?.disconnect(); if (reconnect.current) clearTimeout(reconnect.current); };
  }, []);
  useEffect(() => {
    if (!open) return;
    void refreshBootstrap().catch(fail);
    const close = (event: KeyboardEvent) => {
      if (document.querySelector('.modal.show, .modal.in')) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        if (drawer) { closeDrawer(); return; }
        if (sidebarOpen && window.innerWidth <= 700) { changeSidebar(false); return; }
        if (fullscreen) changeFullscreen(false);
        else { setOpen(false); document.querySelector<HTMLButtonElement>('#zebra-erpnext-root .ze-launch')?.focus(); }
      }
      if ((fullscreen || drawer) && event.key === 'Tab') {
        const items = Array.from(document.querySelectorAll<HTMLElement>('#zebra-erpnext-root .ze-panel button:not(:disabled), #zebra-erpnext-root .ze-panel select:not(:disabled), #zebra-erpnext-root .ze-panel input:not(:disabled), #zebra-erpnext-root .ze-panel textarea:not(:disabled), #zebra-erpnext-root .ze-panel a[href], #zebra-erpnext-root .ze-panel summary')).filter(el => el.getClientRects().length && !el.closest('[inert]') && (!drawer || !!el.closest('.ze-drawer')));
        const first = items[0], last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [open, fullscreen, present, drawer, sidebarOpen]);
  useEffect(() => {
    if (!open || !fullscreen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    document.querySelector<HTMLButtonElement>('#zebra-erpnext-root [data-ze-fullscreen]')?.focus();
    return () => { document.body.style.overflow = previous; };
  }, [open, fullscreen, present]);

  useEffect(() => {
    if (drawer) document.querySelector<HTMLButtonElement>('#zebra-erpnext-root .ze-drawer-close')?.focus();
  }, [drawer]);
  useEffect(() => {
    if (open && fullscreen && sidebarOpen && window.innerWidth <= 700) document.querySelector<HTMLButtonElement>('#zebra-erpnext-root .ze-sidebar header button')?.focus();
  }, [open, fullscreen, sidebarOpen]);

  async function attachClient(surface: any, name: string) {
    runtime.current?.disconnect(); runtime.current = null;
    if (!surface) return;
    if (location.protocol !== 'https:') { setNotice('页面操作需要 HTTPS；聊天与业务查询仍可使用。'); return; }
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
      markNavigation: target => { navigationTarget.current = target; },
    });
    runtime.current = client;
    await client.start();
  }

  async function watch(name: string) {
    stream.current?.abort();
    const controller = new AbortController(); stream.current = controller;
    try {
      const query = new URLSearchParams({ conversation: name, cursor: cursor.current });
      const response = await fetch(`/api/method/zebra_erpnext.api.events?${query}`, { credentials: 'same-origin', signal: controller.signal,
        headers: { Accept: 'text/event-stream' } });
      if (!response.ok || !response.body || !response.headers.get('content-type')?.includes('text/event-stream')) throw new Error('事件连接失败，请重新连接');
      const parse = sseParser((event: any, id: string) => {
        if (activeConversation.current !== name || controller.signal.aborted) return;
        if (id) cursor.current = id;
        if (event.type === 'OBSERVATION_ERROR') throw new Error('事件连接中断，请重新连接已有任务');
        setState((previous: any) => reduceEvent(previous, event));
        if (event.type === 'RUN_ERROR') setError(event.message || '执行失败');
        if (['RUN_FINISHED', 'RUN_ERROR', 'CUSTOM', 'TOOL_CALL_END'].includes(event.type)) { void refreshApprovals(name); void refreshResources(name); }
      });
      const reader = response.body.getReader(), decoder = new TextDecoder();
      while (!controller.signal.aborted) { const { value, done } = await reader.read(); if (done) break; parse(decoder.decode(value, { stream: true })); }
      parse(decoder.decode(), true);
      // ponytail: reconcile the durable snapshot after a finite tail; no automatic mutation retry.
      if (!controller.signal.aborted && activeConversation.current === name) {
        const snapshot = await api('snapshot', { conversation: name });
        if (activeConversation.current !== name || controller.signal.aborted) return;
        setState({ ...initial, ...snapshot });
        if (isActive(snapshot.status)) reconnect.current = setTimeout(() => void watch(name), 1800);
      }
    } catch (error) { if (!controller.signal.aborted && activeConversation.current === name) { fail(error); setNotice('连接中断；点击“重新连接”恢复已有任务，不会重复提交。'); } }
  }

  async function select(name: string, preserveDraft = false) {
    if (savingSettings) return;
    const epoch = ++viewEpoch.current; setOpenedArtifact('');
    if (!preserveDraft) {
      drafts.current.set(activeConversation.current, {text:textRef.current,files:filesRef.current,pending:pending.current});
      const saved = drafts.current.get(name);
      draftEpoch.current += 1; setReadingFiles(false); setPreview('');
      filesRef.current = saved?.files || []; setAttachments(filesRef.current); changeText(saved?.text || ''); pending.current = saved?.pending || null;
    }
    setDrawer(''); setReceipt(null); setConfirming(''); stopGate.current = null; setStopping(false); setCatalog(null); setUsage(null); setArtifacts(null);
    sessionStorage.setItem(`zebra-erpnext:selected:${window.frappe.session.user}`, name);
    activeConversation.current = name; setSelected(name); cursor.current = ''; stream.current?.abort();
    if (reconnect.current) clearTimeout(reconnect.current);
    runtime.current?.disconnect(); runtime.current = null; setApprovals([]); setError(''); setNotice(''); setState(initial);
    void refreshResources(name);
    if (window.innerWidth <= 700) changeSidebar(false);
    if (!name) { setModel(boot?.model_profile || 'deepseek-v4-flash-executor-v1'); setReasoning('high'); setLoadingSettings(false); return; }
    setLoadingSettings(true);
    const conversation = conversations.find(item => item.name === name);
    if (conversation?.company) setCompany(conversation.company);
    try {
      const saved = await api('conversation_settings', { conversation: name });
      if (activeConversation.current !== name || epoch !== viewEpoch.current) return;
      setModel(saved.model_profile); setReasoning(saved.reasoning_effort); setCompany(saved.company);
      const snapshot = await api('snapshot', { conversation: name });
      if (activeConversation.current !== name || epoch !== viewEpoch.current) return;
      if (pending.current?.conversation === name) {
        if (pending.current.request_id === snapshot.accepted_request_id) {
          if (!pending.current.synthetic) clearDraft(); else pending.current = null;
        } else if (pending.current.request_id === snapshot.rejected_request_id) pending.current = null;
      }
      setState({ ...initial, ...snapshot }); setLoadingSettings(false);
      await refreshApprovals(name);
      if (activeConversation.current !== name || epoch !== viewEpoch.current) return;
      if (snapshot.client_surface) await attachClient(snapshot.client_surface, name);
      if (isActive(snapshot.status)) void watch(name);
    } catch (error) { if (activeConversation.current === name && epoch === viewEpoch.current) {setLoadingSettings(false); fail(error);} }
  }

  async function observe() {
    const name = selected, epoch = viewEpoch.current;
    try { await refreshBootstrap(); if (isCurrentView(name,epoch,activeConversation.current,viewEpoch.current)) await select(name); }
    catch (error) { if (isCurrentView(name,epoch,activeConversation.current,viewEpoch.current)) fail(error); }
  }

  async function saveSettings(nextModel: string, nextReasoning: string) {
    if (savingSettings || loadingSettings) return;
    const previous = { model, reasoning };
    setSavingSettings(true); setError('');
    try {
      validateAttachmentBatch(filesRef.current.map(item => item.file), nextModel);
      const name = selected || await create(true);
      setModel(nextModel); setReasoning(nextReasoning);
      await api('save_conversation_settings', { conversation: name, model_profile: nextModel, reasoning_effort: nextReasoning });
    } catch (error) { setModel(previous.model); setReasoning(previous.reasoning); fail(error); }
    finally { setSavingSettings(false); }
  }

  async function create(preserveDraft = false) {
    const conversation = await api('create_conversation', { title: '新会话', company });
    setConversations(previous => [conversation, ...previous]);
    await select(conversation.name, preserveDraft); return conversation.name;
  }
  async function renameConversation(item: any) {
    const dialog = window.frappe.prompt({ fieldname: 'title', fieldtype: 'Data', label: '会话名称', reqd: 1, default: item.title }, async (values: any) => {
      setManaging(true);
      try { const row = await api('rename_conversation', { conversation: item.name, title: values.title });
        setConversations(previous => previous.map(value => value.name === row.name ? { ...value, title: row.title } : value));
      } catch (error) { fail(error); } finally { setManaging(false); }
    }, '重命名会话', '保存');
    animateAgentDialog(dialog);
  }
  function deleteConversation(item: any) {
    const dialog = window.frappe.confirm(`删除“${window.frappe.utils.escape_html(item.title || '新会话')}”？会话将从列表移除，待确认操作将失效，业务单据不受影响。`, async () => {
      setManaging(true);
      try { await api('delete_conversation', { conversation: item.name });
        setConversations(previous => previous.filter(value => value.name !== item.name));
        if (activeConversation.current === item.name) await select('');
        for (const file of drafts.current.get(item.name)?.files || []) releaseDraftUrl(file.url); drafts.current.delete(item.name);
      } catch (error) { fail(error); } finally { setManaging(false); }
    });
    animateAgentDialog(dialog);
  }
  async function send(prompt?: string) {
    const synthetic = typeof prompt === 'string', message = (synthetic ? prompt : textRef.current).trim();
    if (!boot?.enabled || boot.admission_paused === true || !message || readingFiles || sendGate.current || savingSettings || loadingSettings || isActive(state.status)) return false;
    sendGate.current = true; setSending(true); setError(''); setNotice('');
    let epoch = viewEpoch.current;
    try {
      const latest = await refreshBootstrap();
      if (!latest.enabled || latest.admission_paused === true) return false;
      if (!synthetic) validateAttachmentBatch(filesRef.current.map(item => item.file), model);
      const draftFiles = synthetic ? [] : filesRef.current.map(item => item.wire), attachment_key = JSON.stringify(draftFiles);
      // Capture immutable inputs before create/select or a settings change.
      const previous = pending.current, chosenModel = model, chosenReasoning = reasoning;
      const name = selected || await create(true); epoch = viewEpoch.current;
      const same = submissionIdentity(previous, name, message, attachment_key);
      const request_id = same ? previous.request_id : crypto.randomUUID();
      const options = same ? { model_profile: previous.model_profile, reasoning_effort: previous.reasoning_effort } : { model_profile: chosenModel, reasoning_effort: chosenReasoning };
      const context = same ? previous.context : JSON.stringify(pageContext());
      pending.current = { conversation: name, message, request_id, ...options, attachments: draftFiles, attachment_key, context, synthetic };
      const response = await api('submit', { conversation: name, message, request_id, ...options, attachments: JSON.stringify(draftFiles), context });
      if (activeConversation.current !== name || epoch !== viewEpoch.current) return;
      pending.current = null;
      void api('conversations').then(setConversations).catch(fail);
      if (!synthetic) clearDraft();
      else if (textRef.current || filesRef.current.length) setNotice('已提交所选文字请求；输入框中的草稿与附件已保留。');
      setState((previous: any) => ({ ...previous, status: response.status || 'accepted', run_state: runStatus(response.status || 'accepted'), messages: [...previous.messages, { id: request_id, role: 'user', content: message, status: 'complete' }] }));
      cursor.current = '';
      try { await attachClient(response.client_surface, name); } catch (error) { if(epoch===viewEpoch.current) fail(error); }
      if(epoch===viewEpoch.current) void watch(name);
      return true;
    } catch (error) { if(epoch===viewEpoch.current) { fail(error); setNotice(`提交结果未知${pending.current?.request_id ? `（请求 ${pending.current.request_id}）` : ''}；重新连接查看任务。再次发送相同内容会复用请求编号。`); } throw error; }
    finally { sendGate.current = false; setSending(false); }
  }
  async function retryFresh() {
    if (!boot?.enabled || boot.admission_paused === true || sendGate.current || !selected) return;
    const name = selected, epoch = viewEpoch.current;
    const previous = state.fresh_retry;
    const unresolved = ['preparing', 'dispatching'].includes(previous?.phase);
    const outcome = state.command_outcome;
    if (!unresolved && outcome?.retry_eligible !== true) return;
    const operation_id = unresolved ? previous.operation_id : crypto.randomUUID();
    const run_id = unresolved ? previous.predecessor_run_id : outcome.run_id;
    const accepted_event_id = unresolved ? previous.predecessor_event_id : outcome.accepted_event_id;
    sendGate.current = true; setSending(true); setError('');
    // Keep the same operation locally even when the RPC response is lost; the
    // durable server intent also supplies it after a cold page refresh.
    try {
      const latest = await refreshBootstrap();
      if (!latest.enabled || latest.admission_paused === true) return;
      setState((value: any) => ({ ...value, fresh_retry: { operation_id, predecessor_run_id: run_id,
        predecessor_event_id: accepted_event_id, phase: 'preparing' } }));
      await api('retry_fresh', { conversation: name, run_id, accepted_event_id, operation_id });
      if (activeConversation.current === name && viewEpoch.current === epoch) await select(name, true);
    } catch (error) {
      if (activeConversation.current === name && viewEpoch.current === epoch) {
        fail(error); setNotice('请重新连接核对原操作；继续时会复用同一请求编号。');
        try { const snapshot = await api('snapshot', { conversation: name });
          if (activeConversation.current === name && viewEpoch.current === epoch) setState({ ...initial, ...snapshot });
        } catch { /* Retain the pinned local operation until an authorized snapshot is available. */ }
      }
    } finally { sendGate.current = false; setSending(false); }
  }
  function pickSuggestion(prompt: string) { void send(prompt).catch(()=>{}); }

  async function confirm(proposal: any) {
    if (confirmationGate.current.has(proposal.name)) return;
    const name = selected, epoch = viewEpoch.current;
    confirmationGate.current.add(proposal.name); setConfirming(proposal.name); setError('');
    const current = () => isCurrentView(name,epoch,activeConversation.current,viewEpoch.current);
    try {
      const result = await api('zebra_erpnext.business.confirm', { proposal_id: proposal.name });
      if (!current()) return;
      setReceipt(confirmationReceipt(result));
      await refreshApprovals(name);
    } catch (error) { if (current()) { fail(error); setNotice('操作失败或结果未知；请先核对单据和审批状态，再决定后续操作。'); } }
    finally { confirmationGate.current.delete(proposal.name); if (current()) setConfirming(''); }
  }
  async function stop() {
    if (stopGate.current || !selected || !isActive(state.status)) return;
    const token = {name:selected,epoch:viewEpoch.current}; stopGate.current = token; setStopping(true); setError('');
    const current = () => isCurrentView(token.name,token.epoch,activeConversation.current,viewEpoch.current);
    try { await api('cancel', {conversation:token.name}); if (current()) setNotice('已请求停止，正在等待任务确认。'); }
    catch (error) { if (current()) { fail(error); setNotice('停止结果未知；请重新连接核对已有任务。'); stopGate.current = null; setStopping(false); } }
  }
  useEffect(() => { if (!isActive(state.status)) { stopGate.current = null; setStopping(false); } }, [state.status]);

  const busy = sending || isActive(state.status);
  const suggestions = contextualSuggestions(page, state.messages || []);
  const latestAnswer = [...(state.messages || [])].reverse().find((message:any)=>message.role==='assistant');
  function renderMessage(message:any) {
    const index = state.messages.findIndex((item:any)=>item.id===message.id);
    const previousUser = state.messages.slice(0,index).reverse().find((item:any)=>item.role==='user');
    const latest = message.id===latestAnswer?.id;
    return <Answer key={`${selected}:${message.id}`} message={message} conversation={selected} api={api} busy={busy} latest={latest} actions={suggestions.quick} onPick={pickSuggestion} onPreview={setOpenedArtifact}
      onRegenerate={async()=>{ if(!latest || busy || !previousUser?.content) throw new Error('只能重新处理最新完整回答对应的文字请求。'); if (await send(previousUser.content) !== true) throw new Error('当前会话尚不能提交，请核对任务状态。'); }}
      onChanged={(result:any)=>setState((previous:any)=>({...previous,messages:previous.messages.map((item:any)=>item.id===result.message_id&&item.digest===result.digest?{...item,...result}:item)}))} />;
  }
  const turns: any[] = [];
  for (const message of state.messages || []) {
    const normalized = { ...message, status: message.status || 'complete' };
    if (message.role === 'user' || !turns.length) turns.push({ id: message.id, status: 'completed', workSegments: [], items: [], ...(message.role === 'user' ? { userMessage: normalized } : {}) });
    if (message.role !== 'user') turns[turns.length - 1].items.push({ id: message.id, kind: 'message', message: normalized });
  }
  if (turns.length) {
    const last = turns[turns.length - 1];
    last.status = busy ? 'running' : ['failed', 'cancelled', 'blocked', 'partial'].includes(state.status) ? state.status : 'completed';
    if (state.activities?.length) last.items.unshift({ id: 'tools', kind: 'activity', segment: { id: 'tools', activities: state.activities } });
  }
  const previewFile = attachments.find(item => item.id === preview);
  const composer = <fieldset className="ze-composer-fieldset" disabled={savingSettings || loadingSettings || readingFiles} onDragOver={event => { if (catalog?.private_uploads) event.preventDefault(); }} onDrop={event => { event.preventDefault(); if (!busy) void chooseFiles(event.dataTransfer.files); }}>
    <AgentComposer maxAttachments={catalog?.private_uploads ? 4 : 0} attachments={attachments} acceptedFileTypes={acceptedFileTypes} busy={busy} pausing={stopping} disabled={!boot?.enabled || boot.admission_paused === true || sending || readingFiles} value={text}
    onValueChange={changeText} onSubmit={() => void send().catch(()=>{})} onPause={() => void stop()}
    canContinue={false} onContinue={noop} onFilesSelected={list => void chooseFiles(list)} onRemoveAttachment={removeAttachment}
    capabilityOptions={[]} capabilityValue="" onCapabilityChange={noop} modelOptions={boot?.model_options || []} modelValue={model} onModelChange={value => void saveSettings(value, reasoning)}
    reasoningOptions={boot?.reasoning_options || []} reasoningValue={reasoning} onReasoningChange={value => void saveSettings(model, value)} queueCount={state.queue_position || 0} suggestions={[]} onSuggestionPick={pickSuggestion}
    metrics={usageMetrics(state.model_usage ? { model_usage: state.model_usage } : usage)} theme="light"
    placeholder={boot?.admission_paused === true ? maintenanceMessage : "向 zebra 提问，或描述你要完成的 ERP 工作…"} labels={{ addAttachment: catalog?.private_uploads ? '选择附件（也可拖放，最多 4 个）' : '此会话暂不支持私人附件', removeAttachment: name => `移除附件：${name}`, send: '发送', pause: '停止', pausing: '停止中', continue: '继续', contextUnavailable: '尚无模型用量', cacheHitRate: '缓存命中率', contextCapacity: '上下文用量', model: '选择模型', capability: '能力', reasoning: '选择思考强度' }} />

    {attachments.length > 0 && <div className="ze-attachment-previews">{attachments.map(item => <button key={item.id} onClick={() => setPreview(preview === item.id ? '' : item.id)}>预览 {item.name}</button>)}</div>}
    {previewFile && <AgentAssetPreview key={previewFile.id} asset={{ artifactId: previewFile.id, fileName: previewFile.name, mimeType: previewFile.wire.media_type }} resolveArtifact={() => ({ artifactId: previewFile.id, mimeType: previewFile.wire.media_type, url: previewFile.url })} maxTextBytes={65536} />}
    {(savingSettings || readingFiles) && <small role="status">{readingFiles ? '正在读取附件…' : '保存配置中…'}</small>}
  </fieldset>;
  const age = (item: any) => Math.max(0, (Date.now() - new Date(String(item.modified || item.creation).replace(' ', 'T') + '+08:00').getTime()) / 3600000);
  const groups = ([['今天', (n: number) => n < 24], ['本周', (n: number) => n >= 24 && n < 168], ['更早', (n: number) => n >= 168 || !Number.isFinite(n)]] as const)
    .map(([label, matches]) => ({ label, items: conversations.filter((item: any) => matches(age(item))) }));
  const pageLabel = page.doctype ? `${page.doctype} / ${page.name}` : page.route.join(' / ') || '工作台';
  const controlDisabled = sending || managing || savingSettings;
  const chatCanvas = <>
      <div className="ze-task-line">
      {boot?.admission_paused === true && <div className="ze-note" role="status">{maintenanceMessage}</div>}
      {error && <div className="ze-error" role="alert">{error}</div>}{notice && <div className="ze-note" role="status">{notice}</div>}
      <AgentRunStatus onRetry={boot?.capabilities?.retry_fresh === true && boot?.enabled && boot.admission_paused !== true ? retryFresh : undefined} state={sending ? { phase: 'submitting', availableActions: [] } : (['ready','created'].includes(state.status) ? runStatus(state.status) : state.run_state || runStatus(state.status))} labels={{ actions: { retry: '重新验证并继续原请求' }, phases: { idle: '等待消息', submitting: '正在提交', accepted: '已接收', running: '执行中', waiting_for_user: '等待补充信息', paused: '已暂停' }, outcomes: { completed: '已完成', failed: '执行失败', cancelled: '已停止', partial: '部分完成', blocked: '需要处理' }, queued: position => position ? `排队中 · ${position}` : '排队中' }} />
      {selected && <button className="ze-reconnect" disabled={sending || savingSettings} onClick={() => void observe()}>重新连接</button>}</div>
      {receipt && <div className="ze-receipt" role="status">{receipt.label}{receipt.doctype && receipt.name && <a href={`/app/${encodeURIComponent(receipt.doctype.toLowerCase().replace(/ /g,'-'))}/${encodeURIComponent(receipt.name)}`} onClick={event => {event.preventDefault();void window.frappe.set_route('Form',receipt.doctype,receipt.name);}}>查看 {receipt.name} ↗</a>}</div>}
      {state.clarification && <div className="ze-note" role="status">任务需要补充信息：{state.clarification.question}。请在输入框回复。</div>}
      <AgentChat renderMessageContent={renderMessage} theme="light" turns={turns} scrollKey={selected} composer={<ComposerDock>{composer}</ComposerDock>}
        renderTurnFooter={turn=>turn.id===turns.at(-1)?.id?<>
          {approvals.length>0&&<section className="ze-inline-approvals" aria-label="待确认业务操作"><Approvals proposals={approvals} api={api} confirming={confirming || approvals.find(item => confirmationGate.current.has(item.name))?.name || ''} onConfirm={(proposal:any) => void confirm(proposal)} /></section>}
          <ResourceFiles key={selected} inline conversation={selected} artifacts={artifacts} api={api} onError={fail} openedId={openedArtifact} onPreviewed={()=>setOpenedArtifact('')} />
          {!busy&&suggestions.followUps.length>0&&<section className="ze-followups" aria-label="继续追问"><h4>继续追问</h4>{suggestions.followUps.map((item:any)=><button key={item.id} onClick={()=>pickSuggestion(item.prompt)}>{item.label}<span aria-hidden>↗</span></button>)}<small>根据当前页面与本轮公开内容提供的建议</small></section>}
        </>:null} latestOutputLabel="查看最新回复"
        emptyState={loadingSettings ? <div className="ze-loading" role="status" aria-label="正在读取会话"><span/><span/><span/>正在读取会话…</div> : <Welcome actions={suggestions.quick} onPick={pickSuggestion} disabled={!boot?.enabled || busy} notice={boot && !boot.enabled ? '管理员尚未启用 zebra 服务。' : ''} />}
        messageLabels={{ assistant: 'zebra', user: '你', streaming: '生成中', failed: '失败', expand: '展开', collapse: '收起', draft: '草稿' }} activityLabels={{ summary: count => `${count} 项执行详情`, running: '执行中', completed: '已完成', failed: '失败', cancelled: '已停止', blocked: '需要处理', ready: '就绪' }} />
      </>;
  return <>
    <LauncherPill hidden={present && fullscreen} open={open} onToggle={() => setOpen(!open)} />
    {present && <aside className={`ze-panel ${fullscreen ? 'ze-panel-fullscreen' : ''}`} aria-label="zebra ERP 助手" role={fullscreen ? 'dialog' : undefined} aria-modal={fullscreen || undefined}>
      {fullscreen ? <WorkbenchShell sidebarOpen={sidebarOpen} onSidebarClose={() => changeSidebar(false)} mainInert={!!drawer || (sidebarOpen && window.innerWidth <= 700)} sidebarInert={!!drawer}
        sidebar={<SessionSidebar groups={groups} selected={selected} search={search} onSearch={setSearch} onCreate={() => void create().catch(fail)} onSelect={(name: string) => void select(name)} onRename={renameConversation} onDelete={deleteConversation} onCollapse={() => changeSidebar(false)} ageOf={age} company={company} companies={boot?.companies} onCompanyChange={(value: string) => { setCompany(value); void select(''); }} controlDisabled={controlDisabled} emptyHint="还没有会话，点击上方开始。" />}>
          <WorkbenchHeader title={conversations.find(item => item.name === selected)?.title || 'zebra · ERP 工作助手'} company={company} sidebarOpen={sidebarOpen} onOpenSidebar={() => changeSidebar(true)} approvalsCount={approvals.length} approvalsExpanded={drawer === 'approvals'} onApprovals={() => openDrawer('approvals')} onResources={() => openDrawer('settings')} fullscreen={fullscreen} onToggleFullscreen={() => changeFullscreen(!fullscreen)} onClose={() => setOpen(false)} />
          <ErpStatusBanner enabled={boot?.enabled} paused={boot?.admission_paused} company={company} pageLabel={pageLabel} />
          {chatCanvas}
        </WorkbenchShell>
      : <CopilotDrawer selected={selected} sessions={conversations} onSessionChange={(name: string) => void select(name)} company={company} companies={boot?.companies} onCompanyChange={(value: string) => { setCompany(value); void select(''); }} onNew={() => void create().catch(fail)} controlDisabled={controlDisabled} enabled={boot?.enabled} paused={boot?.admission_paused} pageLabel={pageLabel} onExpand={() => changeFullscreen(true)} onClose={() => setOpen(false)} onSettings={() => openDrawer('settings')} approvalsCount={approvals.length} onApprovals={() => openDrawer('approvals')}>
          {chatCanvas}
        </CopilotDrawer>}
      {drawer && <><button className="ze-drawer-backdrop" aria-label="收起详情" onClick={closeDrawer} /><aside className={`ze-drawer ${drawer === 'settings' ? 'ze-drawer--wide' : ''}`} role="dialog" aria-modal="true" aria-label={drawer === 'approvals' ? '确认业务变更' : 'Agent 设置'}><header><strong>{drawer === 'approvals' ? '确认业务变更' : 'Agent 设置'}</strong><button className="ze-drawer-close" aria-label="收起详情" onClick={closeDrawer}>×</button></header><div className="ze-drawer-scroll">
        {drawer === 'approvals' ? <Approvals proposals={approvals} api={api} confirming={confirming || approvals.find(item => confirmationGate.current.has(item.name))?.name || ''} onConfirm={(proposal:any) => void confirm(proposal)} /> : <SettingsPanel key={selected} conversation={selected} catalog={catalog} artifacts={artifacts} api={api} onError={fail} onNew={() => { if (!sending && !savingSettings) void create().catch(fail); }} page={page} />}
      </div><footer><button onClick={closeDrawer}>稍后处理</button><small>{drawer === 'approvals' ? '确认仅执行所展示的原始操作，不会自动追问模型。' : '设置只调整能力可用性，不改变已有任务权限。'}</small></footer></aside></>}
    </aside>}
  </>;
}

function mount() {
  if (window.__zebraERP || !window.frappe?.boot || window.frappe.session?.user === 'Guest' || !/^\/(desk|app)(\/|$)/.test(location.pathname)) return;
  window.__zebraERP = true;
  const root = document.createElement('div'); root.id = 'zebra-erpnext-root'; document.body.append(root); createRoot(root).render(<Panel />);
}
if (window.frappe?.ready) window.frappe.ready(mount);
const readyTimer = setInterval(() => { mount(); if (window.__zebraERP) clearInterval(readyTimer); }, 500);
