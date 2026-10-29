// Shared by the browser and the small Node regression check.
export function sseParser(onEvent) {
  let buffer = '';
  return (chunk, finish = false) => {
    buffer += chunk;
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() || '';
    if (finish && buffer.trim()) { frames.push(buffer); buffer = ''; }
    for (const frame of frames) {
      const lines = frame.split(/\r?\n/);
      const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).replace(/^ /, '')).join('\n');
      const id = lines.find(line => line.startsWith('id:'))?.slice(3).trim();
      if (!data || data === '[DONE]') continue;
      onEvent(JSON.parse(data), id);
    }
  };
}

export function reduceEvent(state, event) {
  const messages = state.messages.map(message => ({ ...message }));
  const activities = [...(state.activities || [])];
  let content_parts = [...(state.content_parts || [])];
  let status = state.status, clarification = state.clarification, model_usage = state.model_usage;
  const publicStatus = value => typeof value === 'string' && ['idle', 'submitting', 'accepted', 'queued', 'running', 'waiting', 'waiting_input', 'awaiting_input', 'awaiting_approval', 'waiting_client_effect', 'suspended', 'paused', 'stopped', 'cancelled', 'completed', 'failed', 'partial', 'blocked', 'awaiting_turn'].includes(value) ? value : status;
  if (event.type === 'TEXT_MESSAGE_START') {
    const existing = messages.find(message => message.id === event.messageId);
    if (existing) { existing.content = ''; existing.status = 'streaming'; }
    else messages.push({ id: event.messageId, role: event.role || 'assistant', content: '', parts: content_parts, status: 'streaming' });
  } else if (event.type === 'TEXT_MESSAGE_CONTENT') {
    let message = messages.find(message => message.id === event.messageId);
    if (!message) { message = { id: event.messageId, role: 'assistant', content: '', status: 'streaming' }; messages.push(message); }
    message.content += event.delta || '';
  } else if (event.type === 'TEXT_MESSAGE_END') {
    const message = messages.find(message => message.id === event.messageId);
    if (message) message.status = 'complete';
  } else if (event.type === 'RUN_STARTED') { status = 'running'; clarification = null; content_parts = []; }
  else if (event.type === 'STATE_SNAPSHOT') { status = publicStatus(event.snapshot?.session?.status); }
  else if (event.type === 'STATE_DELTA') {
    for (const patch of Array.isArray(event.delta) ? event.delta : []) {
      if (!['add', 'replace'].includes(patch.op)) continue;
      if (patch.path === '/session/status') status = publicStatus(patch.value);
      else if (patch.path === '/session') status = publicStatus(patch.value?.status);
    }
  } else if (event.type === 'CUSTOM' && event.name === 'zebra.content_part') {
    const part = normalizeParts([event.value?.part])[0];
    if (part) {
      content_parts = [...content_parts.filter(item=>item.id!==part.id),part].slice(-16);
      const message = [...messages].reverse().find(item=>item.role==='assistant'&&item.status==='streaming');
      if(message)message.parts=content_parts;
    }
  } else if (event.type === 'CUSTOM' && event.name === 'zebra.model_usage' && event.value && typeof event.value === 'object') {
    const value = event.value; model_usage = { input_tokens: value.input_tokens, input_token_limit: value.input_token_limit, cache_hit_tokens: value.prompt_cache_hit_tokens, cache_miss_tokens: value.prompt_cache_miss_tokens };
  } else if (event.type === 'RUN_FINISHED') {
    const interrupts = Array.isArray(event.outcome?.interrupts) ? event.outcome.interrupts : [];
    const question = interrupts.find(item => item.reason === 'clarification_required');
    if (question) { status = 'waiting_input'; clarification = { clarification_id: String(question.toolCallId || question.tool_call_id || question.id || '').slice(0, 255), question: String(question.message || '').slice(0, 10000), choices: [] }; }
    else if (interrupts.some(item => item.reason === 'approval_required')) status = 'awaiting_approval';
    else status = interrupts.length ? 'suspended' : 'completed';
  }
  else if (event.type === 'RUN_ERROR') status = 'failed';
  else if (event.type === 'TOOL_CALL_START') activities.push({ activityId: event.toolCallId, kind: 'tool', title: event.toolCallName || '调用工具', status: 'running' });
  else if (event.type === 'TOOL_CALL_END') {
    const index = activities.findIndex(activity => activity.activityId === event.toolCallId);
    if (index >= 0) activities[index] = { ...activities[index], status: 'completed' };
  }
  return { ...state, messages, activities, status, clarification, model_usage, content_parts, run_state: runStatus(status) };
}

export function assertCurrentForm(expected, current, form) {
  if (!expected || typeof expected.doctype !== 'string' || typeof expected.name !== 'string' || !Array.isArray(expected.route)) throw new Error('缺少明确的页面、单据类型或单据编号');
  if (JSON.stringify(expected.route) !== JSON.stringify(current.route) || expected.doctype !== current.doctype || expected.name !== current.name) throw new Error('页面已变化，请重新请求填写');
  if (!form?.doc || form.doc.doctype !== expected.doctype || form.doc.name !== expected.name || typeof form.set_value !== 'function') throw new Error('当前 ERPNext 页面不支持安全表单填写；请先打开标准单据表单');
  if (form.doc.docstatus !== 0) throw new Error('仅允许填写草稿单据');
}

const FILE_TYPES = {
  txt: 'text/plain', md: 'text/markdown', csv: 'text/csv', json: 'application/json',
  pdf: 'application/pdf', docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif',
};
export const acceptedFileTypes = Object.keys(FILE_TYPES).map(extension => `.${extension}`).join(',');
export function attachmentInfo(file, model) {
  if (!file.name || file.name.length > 180 || /[\\/\x00-\x1f\x7f]/.test(file.name)) throw new Error('附件文件名无效');
  const mime = FILE_TYPES[file.name.split('.').pop().toLowerCase()];
  if (!mime || (file.type && file.type !== 'application/octet-stream' && file.type !== mime && !(mime === 'text/markdown' && file.type === 'text/plain')))
    throw new Error(`不支持的附件类型：${file.name}`);
  const kind = mime.startsWith('image/') ? 'image' : mime.startsWith('text/') || mime === 'application/json' ? 'text' : 'document';
  const limit = { image: 16777216, text: 65536, document: 4194304 }[kind];
  if (!Number.isSafeInteger(file.size) || file.size <= 0 || file.size > limit) throw new Error(`${file.name} 超过附件大小限制或为空`);
  if (kind === 'image' && model.includes('-pro-')) throw new Error('Pro 模型不支持图片；请移除图片或选择 Flash 模型');
  return { mime, kind, limit };
}
export function validateAttachmentBatch(files, model) {
  if (files.length > 4) throw new Error('每条消息最多添加 4 个附件');
  const totals = { image: 0, text: 0, document: 0 };
  for (const file of files) { const { kind } = attachmentInfo(file, model); totals[kind] += file.size; }
  if (totals.image > 33554432 || totals.text > 131072 || totals.document > 8388608) throw new Error('附件合计大小超过限制');
}
export function usageMetrics(value) {
  const usage = value?.model_usage || {};
  const finite = number => typeof number === 'number' && Number.isFinite(number) && number >= 0 ? number : null;
  const contextTokens = finite(usage.input_tokens), contextLimit = finite(usage.input_token_limit);
  const hit = finite(usage.cache_hit_tokens), miss = finite(usage.cache_miss_tokens);
  return { contextTokens, contextLimit, contextPercent: contextLimit > 0 && contextTokens !== null ? contextTokens / contextLimit : null,
    cacheHitRate: hit !== null && miss !== null && hit + miss > 0 ? hit / (hit + miss) : null };
}
export function artifactDownloadUrl(conversation, artifactId) {
  return `/api/method/zebra_erpnext.api.artifact_download?${new URLSearchParams({ conversation, artifact_id: artifactId })}`;
}

export function runStatus(status) {
  if (status === 'stopped') status = 'cancelled';
  if (['completed', 'failed', 'cancelled', 'partial', 'blocked'].includes(status)) return { phase: 'terminal', outcome: status, availableActions: [] };
  return { phase: ({ awaiting_turn: 'idle', suspended: 'paused', awaiting_approval: 'waiting_for_user', waiting: 'waiting_for_user', waiting_input: 'waiting_for_user', awaiting_input: 'waiting_for_user', waiting_client_effect: 'waiting_for_user' })[status] || (['idle', 'submitting', 'accepted', 'queued', 'running', 'paused'].includes(status) ? status : 'idle'), availableActions: [] };
}

// ponytail: previews use a closed MIME/extension list; unknown active formats remain download-only.
export function safePreviewMime(name, mime) {
  if (typeof name !== 'string' || typeof mime !== 'string') return null;
  const expected = FILE_TYPES[name.split('.').pop().toLowerCase()];
  return expected === mime && ['text/plain', 'text/markdown', 'text/csv', 'application/json', 'application/pdf', 'image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(mime) ? mime : null;
}


export function artifactPreviewUrl(conversation, artifactId) {
  return `/api/method/zebra_erpnext.api.artifact_preview?${new URLSearchParams({ conversation, artifact_id: artifactId })}`;
}
export function reportDownloadUrl(conversation, message) {
  return `/api/method/zebra_erpnext.api.report_download?${new URLSearchParams({ conversation, message_id: message.id, digest: message.digest })}`;
}
export function fileArtifacts(rows) {
  return (Array.isArray(rows) ? rows : []).filter(item => typeof item?.delivery?.file_name === 'string' && item.delivery.file_name && !/[\\/\x00-\x1f\x7f]/.test(item.delivery.file_name) && ['file', 'image', 'video', 'document', 'report', 'artifact', 'attachment', 'chart'].includes(item.kind));
}
export function normalizeParts(parts) {
  return (Array.isArray(parts) ? parts : []).slice(0, 16).flatMap(part => {
    if (!part || typeof part.id !== 'string' || !['text', 'file', 'image', 'video', 'chart', 'external_video', 'external-video'].includes(part.type)) return [];
    const base = {id: part.id.slice(0,200), type: part.type, state: ['ready','failed','processing'].includes(part.state) ? part.state : 'ready'};
    if (part.type === 'text') return typeof part.text === 'string' ? [{...base, text: part.text.slice(0,100000), format: part.format === 'markdown' ? 'markdown' : 'plain'}] : [];
    if (['external_video', 'external-video'].includes(part.type)) {
      try { const url = new URL(part.sourceUrl || part.url); const providers={'youtube.com':'youtube','www.youtube.com':'youtube','youtu.be':'youtube','bilibili.com':'bilibili','www.bilibili.com':'bilibili','vimeo.com':'vimeo','www.vimeo.com':'vimeo','player.vimeo.com':'vimeo'}; return url.protocol==='https:'&&!url.username&&!url.password&&(!url.port||url.port==='443')&&providers[url.hostname] ? [{...base,type:'external-video',provider:providers[url.hostname],url:url.href,title:String(part.title||'视频').slice(0,255)}] : []; } catch { return []; }
    }
    if (part.type === 'chart') {
      if (part.specType !== 'vega-lite' || !String(part.specVersion).startsWith('6')) return [];
      const result = {...base, specType:'vega-lite',specVersion:'6',title:String(part.title || '图表').slice(0,255),description:String(part.description || '').slice(0,500)};
      for (const key of ['specArtifactId','dataArtifactId','fallbackImageArtifactId','fallbackTableArtifactId']) if (/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/.test(part[key] || '')) result[key]=part[key];
      if (part.spec && typeof part.spec === 'object' && JSON.stringify(part.spec).length <= 32768) result.spec=part.spec;
      return [result];
    }
    if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/.test(part.artifactId || '') || typeof part.mimeType !== 'string') return [];
    const name=String(part.fileName || part.name || '').slice(0,255);
    if (!name || /[\\/\x00-\x1f\x7f]/.test(name)) return [];
    if (part.type === 'image' && (!part.mimeType.startsWith('image/') || safePreviewMime(name,part.mimeType) !== part.mimeType)) return [];
    if (part.type === 'video' && !({mp4:'video/mp4',webm:'video/webm',ogg:'video/ogg'}[name.split('.').pop().toLowerCase()] === part.mimeType)) return [];
    return [{...base, artifactId:part.artifactId,mimeType:part.mimeType,fileName:name,name,alt:String(part.alt || name).slice(0,500),title:String(part.title || name).slice(0,500),description:String(part.description || '').slice(0,500),...(Number.isSafeInteger(part.sizeBytes)&&part.sizeBytes>=0 ? {sizeBytes:part.sizeBytes}:{})}];
  });
}
// ponytail: explicit ERP prompts need no second model call. Their inputs contain
// only current route coordinates and the public turn, never invented balances.
export function contextualSuggestions(page, messages) {
  const answer = [...messages].reverse().find(message => message.role === 'assistant' && message.digest);
  const target = page?.doctype && page?.name ? `${page.doctype} / ${page.name}` : (page?.route || []).join(' / ') || 'ERP 工作台';
  const scope = `当前页面：${target}。仅使用当前用户有权读取的资料；先查询，不自动修改或批准业务。`;
  return { quick: [
    {id:'inspect',label:page?.doctype?'核对当前单据':'查看可用业务',prompt:`${scope} ${page?.doctype?'请核对当前单据的状态、关键字段和需要关注的问题。':'请列出我当前有权限查询和处理的业务，说明可用的下一步。'}`},
    {id:'summary',label:'整理工作摘要',prompt:`${scope} ${answer?'请结合上一轮公开回答整理已确认事实、未核实信息和下一步检查项。':'请说明本页面通常需要核对哪些信息；没有读取的数据请明确标注未知。'}`},
  ], followUps: answer ? [
    {id:'evidence',label:'这些结论有哪些依据？',prompt:`${scope} 请逐项列出上一轮回答的依据，区分已读取的单据、推断和待核实信息，不添加未经查询的业务事实。`},
    {id:'next',label:'下一步需要检查什么？',prompt:`${scope} 基于上一轮回答，列出下一步可执行的检查清单；如涉及业务写入，仅说明方案并等待我独立确认。`},
  ] : [] };
}
export function visibleContent(content) { return String(content || '').replace(/artifact:\/\/[^\s)\]<>]+/g, '（成果见文件区）'); }
export function safeSources(value) {
  return (Array.isArray(value) ? value : []).slice(0,20).flatMap(item => {
    try { const url = new URL(item.url); return url.protocol === 'https:' && !url.username && !url.password ? [{title:String(item.title || item.label || url.hostname).slice(0,255),url:url.href}] : []; } catch { return []; }
  });
}
export function submissionIdentity(pending, conversation, message, attachmentKey) {
  if (!pending) return false;
  if (pending.conversation !== conversation || pending.message !== message || pending.attachment_key !== attachmentKey) throw new Error('上一条提交结果尚未确认，请重新连接核对；重试时请保持原文字和附件。');
  return true;
}

export function answerBody(message) { const text=normalizeParts(message.parts).filter(part=>part.type==='text').map(part=>part.text); return visibleContent(text.length?text.join('\n\n'):message.content); }
