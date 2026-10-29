import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AgentChat, AgentComposer, AgentAssetPreview, AgentRunStatus } from '@zebra-agent/react';
import { ZebraClientRuntime } from '@zebra-agent/client-core';
import '@zebra-agent/react/styles.css';
import './style.css';
import { gsap, Flip, motionAllowed, installAgentMotion, animateAgentDialog } from './motion';
import { Resources, ResourceFiles } from './resources';
import { Answer } from './answer';
import { sseParser, reduceEvent, assertCurrentForm, attachmentInfo, validateAttachmentBatch, acceptedFileTypes, usageMetrics, runStatus, contextualSuggestions, submissionIdentity } from './protocol.mjs';

declare global { interface Window { frappe: any; cur_frm: any; __zebraERP?: boolean; } }
const api = (method: string, args: Record<string, unknown> = {}) => new Promise<any>((resolve, reject) => {
  window.frappe.call({ method: method.includes('.') ? method : `zebra_erpnext.api.${method}`, args,
    callback: (result: any) => result.exc ? reject(new Error('ERPNext 请求失败')) : resolve(result.message),
    error: () => reject(new Error('请求失败，请检查登录状态或网络连接')) });
});
function pageContext() {
  const route = window.frappe.get_route?.() || [];
  return { route, doctype: route[0] === 'Form' ? route[1] : null, name: route[0] === 'Form' ? route[2] : null };
}
const isActive = (status: string) => ['running', 'queued', 'accepted', 'waiting', 'waiting_client_effect', 'submitting'].includes(status);
const noop = () => {};
const initial = { messages: [], activities: [], status: 'idle' };


function Panel() {
  const [open, setOpen] = useState(false), [fullscreen, setFullscreen] = useState(false);
  const [present, setPresent] = useState(false);
  const layout = useRef<any>(null), viewEpoch = useRef(0), sendGate = useRef(false);
  const [openedArtifact, setOpenedArtifact] = useState('');
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
  function fail(error: unknown) { setError(error instanceof Error ? error.message : '请求失败'); }
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
    const sidebar = document.querySelector('#zebra-erpnext-root .ze-sidebar');
    const apply = () => {
      const main = document.querySelector('#zebra-erpnext-root .ze-main');
      if (main && motionAllowed()) layout.current = Flip.getState(main);
      setSidebarOpen(value);
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
    for (const url of draftUrls.current) URL.revokeObjectURL(url); draftUrls.current.clear();
    filesRef.current = []; setAttachments([]); setPreview(''); setText(''); setReadingFiles(false); pending.current = null;
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
      setText(value => value || '请阅读附件并说明内容。');
    } catch (error) { added.forEach(item => releaseDraftUrl(item.url)); if (draftEpoch.current === epoch) fail(error); }
    finally { if (draftEpoch.current === epoch) setReadingFiles(false); }
  }
  function removeAttachment(id: string) {
    const item = filesRef.current.find(item => item.id === id); if (item) releaseDraftUrl(item.url);
    filesRef.current = filesRef.current.filter(item => item.id !== id); setAttachments(filesRef.current); if (preview === id) setPreview('');
  }
  async function refreshApprovals(name: string) {
    const epoch = viewEpoch.current;
    const list = await api('approvals', { conversation: name });
    if (activeConversation.current === name && epoch === viewEpoch.current) setApprovals(list || []);
  }
  useEffect(() => {
    void refreshResources('');
    api('bootstrap').then(value => { setBoot(value); setModel(value.model_profile); setReasoning(value.reasoning_effort); setCompany(value.company || ''); return api('conversations'); }).then(rows => { setConversations(rows); const name = sessionStorage.getItem(`zebra-erpnext:selected:${window.frappe.session.user}`); if (rows.some((row: any) => row.name === name)) void select(name!); }).catch(fail);
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
    const close = (event: KeyboardEvent) => {
      if (document.querySelector('.modal.show, .modal.in')) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        if (fullscreen) changeFullscreen(false);
        else { setOpen(false); document.querySelector<HTMLButtonElement>('#zebra-erpnext-root .ze-launch')?.focus(); }
      }
      if (fullscreen && event.key === 'Tab') {
        const items = Array.from(document.querySelectorAll<HTMLElement>('#zebra-erpnext-root .ze-panel button:not(:disabled), #zebra-erpnext-root .ze-panel select:not(:disabled), #zebra-erpnext-root .ze-panel textarea:not(:disabled), #zebra-erpnext-root .ze-panel a[href], #zebra-erpnext-root .ze-panel summary')).filter(el => el.getClientRects().length);
        const first = items[0], last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [open, fullscreen, present]);
  useEffect(() => {
    if (!open || !fullscreen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    document.querySelector<HTMLButtonElement>('#zebra-erpnext-root [data-ze-fullscreen]')?.focus();
    return () => { document.body.style.overflow = previous; };
  }, [open, fullscreen, present]);

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
    client.registry.mount('erpnext.ui.document.open', async args => {
      if (typeof args.doctype !== 'string' || typeof args.name !== 'string' || !args.doctype || !args.name) throw new Error('单据参数无效');
      const target = { doctype: args.doctype, name: args.name };
      navigationTarget.current = target;
      try {
        await window.frappe.set_route('Form', args.doctype, args.name);
        const current = pageContext();
        if (current.doctype !== target.doctype || current.name !== target.name) throw new Error('单据页面未能打开');
        return { opened: true, ...target, route: current.route };
      } finally {
        // The authorized navigation itself must not invalidate its own receipt.
        // Advance the fence after the SDK's post-handler check, before any next action.
        setTimeout(() => {
          if (navigationTarget.current === target) navigationTarget.current = null;
          client.uiRevision.bump();
        }, 0);
      }
    });
    client.registry.mount('erpnext.ui.form.fill', async args => {
      const expected = { route: args.route, doctype: args.doctype, name: args.name };
      const values = args.values;
      assertCurrentForm(expected, pageContext(), window.cur_frm);
      if (!values || typeof values !== 'object' || Array.isArray(values)) throw new Error('填写字段无效');
      const form = window.cur_frm, atRevision = revision.current;
      for (const [field, value] of Object.entries(values)) {
        const meta = form.get_docfield?.(field);
        if (!meta || meta.read_only || meta.hidden || Number(meta.permlevel || 0) > 0 || ['name', 'doctype', 'owner', 'docstatus'].includes(field) || (value !== null && !['string', 'number', 'boolean'].includes(typeof value))) throw new Error(`字段不可安全填写：${field}`);
      }
      for (const [field, value] of Object.entries(values)) {
        assertCurrentForm(expected, pageContext(), window.cur_frm);
        if (atRevision !== revision.current) throw new Error('页面已变化，停止填写');
        await form.set_value(field, value);
      }
      return { filled: Object.keys(values), saved: false };
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
        if (['RUN_FINISHED', 'RUN_ERROR', 'CUSTOM', 'TOOL_CALL_END'].includes(event.type)) { void refreshApprovals(name).catch(fail); void refreshResources(name); }
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
    if (!preserveDraft && pending.current?.conversation !== name) clearDraft(); setCatalog(null); setUsage(null); setArtifacts(null);
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
      setModel(saved.model_profile); setReasoning(saved.reasoning_effort); setCompany(saved.company); setLoadingSettings(false);
      const snapshot = await api('snapshot', { conversation: name });
      if (activeConversation.current !== name || epoch !== viewEpoch.current) return;
      if (pending.current?.conversation === name) {
        if (pending.current.request_id === snapshot.accepted_request_id) {
          if (!pending.current.synthetic) clearDraft(); else pending.current = null;
        } else if (pending.current.request_id === snapshot.rejected_request_id) pending.current = null;
      }
      setState({ ...initial, ...snapshot });
      await refreshApprovals(name);
      if (activeConversation.current !== name || epoch !== viewEpoch.current) return;
      if (snapshot.client_surface) await attachClient(snapshot.client_surface, name);
      if (isActive(snapshot.status)) void watch(name);
    } catch (error) { if (activeConversation.current === name && epoch === viewEpoch.current) fail(error); }
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
      } catch (error) { fail(error); } finally { setManaging(false); }
    });
    animateAgentDialog(dialog);
  }
  async function send(prompt?: string) {
    const synthetic = typeof prompt === 'string', message = (synthetic ? prompt : text).trim();
    if (!message || readingFiles || sendGate.current || savingSettings || loadingSettings || isActive(state.status)) return false;
    sendGate.current = true; setSending(true); setError(''); setNotice('');
    let epoch = viewEpoch.current;
    try {
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
      else if (text || filesRef.current.length) setNotice('已提交所选文字请求；输入框中的草稿与附件已保留。');
      setState((previous: any) => ({ ...previous, status: 'running', messages: [...previous.messages, { id: request_id, role: 'user', content: message, status: 'complete' }] }));
      cursor.current = '';
      try { await attachClient(response.client_surface, name); } catch (error) { if(epoch===viewEpoch.current) fail(error); }
      if(epoch===viewEpoch.current) void watch(name);
      return true;
    } catch (error) { if(epoch===viewEpoch.current) { fail(error); setNotice('提交结果未知时，重新连接查看任务；再次发送相同内容会复用请求编号。'); } throw error; }
    finally { sendGate.current = false; setSending(false); }
  }
  function pickSuggestion(prompt: string) { void send(prompt).catch(()=>{}); }

  async function confirm(proposal: any) {
    setConfirming(proposal.name); setError('');
    try {
      const result = await api('zebra_erpnext.business.confirm', { proposal_id: proposal.name });
      setNotice(`操作结果：${JSON.stringify(result)}`);
      await refreshApprovals(selected);
    } catch (error) { fail(error); setNotice('操作失败或结果未知；请先核对单据和审批状态，再决定后续操作。'); }
    finally { setConfirming(''); }
  }

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
    <AgentComposer maxAttachments={catalog?.private_uploads ? 4 : 0} attachments={attachments} acceptedFileTypes={acceptedFileTypes} busy={busy} pausing={false} disabled={!boot?.enabled || sending || readingFiles} value={text}
    onValueChange={setText} onSubmit={() => void send().catch(()=>{})} onPause={() => { api('cancel', { conversation: selected }).then(() => setNotice('已请求停止，正在等待任务确认。')).catch(fail); }}
    canContinue={false} onContinue={noop} onFilesSelected={list => void chooseFiles(list)} onRemoveAttachment={removeAttachment}
    capabilityOptions={[]} capabilityValue="" onCapabilityChange={noop} modelOptions={boot?.model_options || []} modelValue={model} onModelChange={value => void saveSettings(value, reasoning)}
    reasoningOptions={boot?.reasoning_options || []} reasoningValue={reasoning} onReasoningChange={value => void saveSettings(model, value)} queueCount={state.queue_position || 0} suggestions={!state.messages?.length && !busy ? suggestions.quick.map((item:any)=>({label:item.label,value:item.prompt})) : []} onSuggestionPick={pickSuggestion}
    metrics={usageMetrics(state.model_usage ? { model_usage: state.model_usage } : usage)} theme="light"
    placeholder="向 Zebra 提问，或描述你要完成的 ERP 工作…" labels={{ addAttachment: catalog?.private_uploads ? '选择附件（也可拖放，最多 4 个）' : '此会话暂不支持私人附件', removeAttachment: name => `移除附件：${name}`, send: '发送', pause: '停止', pausing: '停止中', continue: '继续', contextUnavailable: '尚无模型用量', cacheHitRate: '缓存命中率', contextCapacity: '上下文用量', model: '选择模型', capability: '能力', reasoning: '选择思考强度' }} />
    {!catalog?.private_uploads && <p className="ze-upload-reason">{catalog?.legacy_workspace?'此历史会话使用共享工作区，不能上传私人附件。':'私人附件接入尚未开放；可继续使用文字与已有成果。'}</p>}
    {attachments.length > 0 && <div className="ze-attachment-previews">{attachments.map(item => <button key={item.id} onClick={() => setPreview(preview === item.id ? '' : item.id)}>预览 {item.name}</button>)}</div>}
    {previewFile && <AgentAssetPreview key={previewFile.id} asset={{ artifactId: previewFile.id, fileName: previewFile.name, mimeType: previewFile.wire.media_type }} resolveArtifact={() => ({ artifactId: previewFile.id, mimeType: previewFile.wire.media_type, url: previewFile.url })} maxTextBytes={65536} />}
    {(savingSettings || readingFiles) && <small role="status">{readingFiles ? '正在读取附件…' : '保存配置中…'}</small>}
  </fieldset>;
  // Adapted from Trench's strategy-session-sidebar: same grouping, rows and actions,
  // using the existing Frappe dialogs instead of importing its app-wide UI stack.
  const age = (item: any) => Math.max(0, (Date.now() - new Date(String(item.modified || item.creation).replace(' ', 'T') + '+08:00').getTime()) / 3600000);
  const groups = [ ['最近', (n: number) => n < 24], ['本周', (n: number) => n >= 24 && n < 168], ['更早', (n: number) => n >= 168 || !Number.isFinite(n)] ] as const;
  return <>
    <button hidden={present && fullscreen} className="ze-launch" aria-label={open ? '关闭 Zebra 助手' : '打开 Zebra 助手'} aria-expanded={open} onClick={() => setOpen(!open)}>Zebra <span>✦</span></button>
    {present && <aside className={`ze-panel ${fullscreen ? 'ze-panel-fullscreen' : ''}`} aria-label="Zebra ERP 助手" role={fullscreen ? 'dialog' : undefined} aria-modal={fullscreen || undefined}>
      {fullscreen && sidebarOpen && <>
        <button className="ze-sidebar-backdrop" aria-label="收起会话列表" onClick={() => setSidebarOpen(false)} />
        <nav className="ze-sidebar" aria-label="会话列表">
          <header><div><p>ZEBRA AI</p><h2>信息会话</h2></div><button aria-label="收起会话列表" onClick={() => setSidebarOpen(false)}>◧</button></header>
          <div className="ze-session-scroll"><button className="ze-create" disabled={sending || managing || savingSettings} onClick={() => void create().catch(fail)}>✎　新建会话</button>
          {groups.map(([label, matches]) => { const items = conversations.filter(item => matches(age(item))); return items.length ? <section key={label}><h3>{label}</h3>{items.map(item => <div key={item.name} className={`ze-session ${selected === item.name ? 'is-selected' : ''}`}>
            <button className="ze-session-select" disabled={sending || managing || savingSettings} aria-current={selected === item.name ? 'page' : undefined} onClick={() => void select(item.name)} title={item.title}><strong>{item.title || '新会话'}</strong><time>{age(item) < 1 ? '刚刚' : `${Math.floor(age(item))}H`}</time></button>
            <details className="ze-session-menu"><summary aria-label={`管理会话：${item.title || '新会话'}`}>•••</summary><div><button disabled={sending || managing || savingSettings} onClick={event => { event.currentTarget.closest('details')?.removeAttribute('open'); void renameConversation(item); }}>重命名</button><button disabled={sending || managing || savingSettings} onClick={event => { event.currentTarget.closest('details')?.removeAttribute('open'); deleteConversation(item); }}>删除</button></div></details>
          </div>)}</section> : null; })}
          {!conversations.length && <p className="ze-session-empty">还没有会话，点击上方开始。</p>}</div>
        </nav></>}
      <div className="ze-main">
      <header className="ze-heading"><div>{fullscreen && !sidebarOpen && <button aria-label="展开会话列表" onClick={() => changeSidebar(true)}>◨</button>}<strong>Zebra</strong><small>ERP 工作助手</small></div><div><button data-ze-fullscreen onClick={() => changeFullscreen(!fullscreen)} aria-label={fullscreen ? '退出全屏' : '全屏显示'} title={fullscreen ? '退出全屏（Esc）' : '全屏显示'}>{fullscreen ? '退出全屏' : '全屏'}</button><button onClick={() => setOpen(false)} aria-label="关闭助手">×</button></div></header>
      <div className="ze-controls"><select aria-label="公司" value={company} disabled={sending || savingSettings} onChange={event => { setCompany(event.target.value); void select(''); }}>{(boot?.companies || []).map((item: any) => <option key={item.name || item} value={item.name || item}>{item.name || item}</option>)}</select>
        <select hidden={fullscreen} aria-label="会话" value={selected} disabled={sending || savingSettings} onChange={event => { if (event.target.value) void select(event.target.value); }}><option value="">选择会话</option>{conversations.map(item => <option key={item.name} value={item.name}>{item.title || item.name}</option>)}</select>
        {!fullscreen && <button disabled={sending || savingSettings} onClick={() => void create().catch(fail)}>新建</button>}</div>
      <div className="ze-context">当前页面 · {page.doctype ? `${page.doctype} / ${page.name}` : page.route.join(' / ') || '工作台'} {selected && <button disabled={sending || savingSettings} onClick={() => void select(selected)}>重新连接</button>}</div>
      {page.doctype && !window.cur_frm?.set_value && <div className="ze-note">当前页面尚不支持安全填写；可继续查询业务或准备需要确认的单据操作。</div>}
      {location.protocol !== 'https:' && <div className="ze-note"><a href="https://192.168.110.42:18443/desk" target="_blank" rel="noreferrer">通过 HTTPS 打开以启用页面操作</a></div>}
      {error && <div className="ze-error" role="alert">{error}</div>}{notice && <div className="ze-note" role="status">{notice}</div>}
      <div className="ze-approvals">{approvals.map(proposal => <section key={proposal.name}><strong>需要你确认：{proposal.operation}</strong><details><summary>查看准确操作参数</summary><pre>{typeof proposal.arguments_json === 'string' ? proposal.arguments_json : JSON.stringify(proposal.arguments_json || proposal.arguments, null, 2)}</pre></details><button disabled={!!confirming} onClick={() => void confirm(proposal)}>{confirming === proposal.name ? '处理中…' : '确认执行此操作'}</button></section>)}</div>
      <Resources key={selected} conversation={selected} catalog={catalog} artifacts={artifacts} api={api} onError={fail} onNew={() => { if (!sending && !savingSettings) void create().catch(fail); }} />
      <AgentRunStatus state={state.run_state || runStatus(sending ? 'submitting' : state.status)} labels={{ phases: { idle: '等待消息', submitting: '正在提交', accepted: '已接收', running: '执行中', waiting_for_user: '等待补充信息', paused: '已暂停' }, outcomes: { completed: '已完成', failed: '执行失败', cancelled: '已停止', partial: '部分完成', blocked: '需要处理' }, queued: position => position ? `排队中 · ${position}` : '排队中' }} />
      {state.clarification && <div className="ze-note" role="status">任务需要补充信息：{state.clarification.question}。请在输入框回复。</div>}
      <AgentChat renderMessageContent={renderMessage} theme="light" turns={turns} scrollKey={selected} composer={composer}
        renderTurnFooter={turn=>turn.id===turns.at(-1)?.id?<>
          <ResourceFiles key={selected} inline conversation={selected} artifacts={artifacts} api={api} onError={fail} openedId={openedArtifact} onPreviewed={()=>setOpenedArtifact('')} />
          {!busy&&suggestions.followUps.length>0&&<section className="ze-followups" aria-label="继续追问"><h4>继续追问</h4>{suggestions.followUps.map((item:any)=><button key={item.id} onClick={()=>pickSuggestion(item.prompt)}>{item.label}<span aria-hidden>↗</span></button>)}<small>根据当前页面与本轮公开内容提供的建议</small></section>}
        </>:null} latestOutputLabel="查看最新回复"
        emptyState={<div className="ze-welcome"><span>✦</span><h2>今天需要处理什么？</h2><p>查询业务、分析数据，或准备单据操作。<br />需要修改数据时，会先展示具体操作供你确认。</p>{boot && !boot.enabled && <p>管理员尚未启用 Zebra 服务。</p>}</div>}
        messageLabels={{ assistant: 'Zebra', user: '你', streaming: '生成中', failed: '失败', expand: '展开', collapse: '收起', draft: '草稿' }} activityLabels={{ summary: count => `${count} 项执行详情`, running: '执行中', completed: '已完成', failed: '失败', cancelled: '已停止', blocked: '需要处理', ready: '就绪' }} />
      </div>
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
