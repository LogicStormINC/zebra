import type { Message, Interrupt } from '@ag-ui/core';
import type { AgentActivity, AgentActivityStatus, AgentDeliveryAssessment, AgentContentPart, AgentInterruptView, AgentMessage, AgentRunState, AgentAgUiFacts } from '@zebra-agent/ui-contracts';

/** Unknown AG-UI arbitrary-data fields are checked here, never dumped into the DOM. */
export function object(value: unknown): { [key: string]: unknown } {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as { [key: string]: unknown } : {};
}
export function text(value: unknown, max = 8192): string | undefined { return typeof value === 'string' ? value.length > max ? value.slice(0, max) + '… [display truncated]' : value : undefined; }
export function activityStatus(value: unknown): AgentActivityStatus {
  return value === 'completed' || value === 'failed' || value === 'cancelled' || value === 'running' ? value : 'ready';
}
export function runState(facts: AgentAgUiFacts): AgentRunState {
  const status = facts.execution;
  if (status === 'completed' || status === 'failed' || status === 'cancelled') return { phase: 'terminal', outcome: status, availableActions: [] };
  return { phase: status === 'paused' ? 'paused' : status === 'waiting_input' ? 'waiting_for_user' : status === 'running' || status === 'resuming' ? 'running' : 'reconciling', availableActions: [],
    ...(status === 'unknown' ? { safeMessage: 'Execution state is not available.' } : {}) };
}
export function publicMessage(message: Message, committed: boolean, ended: boolean, parts: readonly AgentContentPart[]): AgentMessage | undefined {
  if (message.role !== 'assistant' && message.role !== 'user') return;
  const content = typeof message.content === 'string' ? message.content : '';
  if (!content && !parts.length) return;
  return { id: message.id, role: message.role, content, ...(message.role === 'assistant' ? { presentation: committed ? 'committed' as const : 'provisional' as const } : {}),
    status: ended || message.role === 'user' ? 'complete' : 'streaming',
    ...(parts.length ? { parts: [...(content ? [{ id: `${message.id}:text`, type: 'text' as const, format: 'markdown' as const, state: ended ? 'ready' as const : 'processing' as const, text: content }] : []), ...parts] } : {}) };
}
export function publicActivity(message: Extract<Message, { role: 'activity' }>, markers: readonly { name: string; status: 'observed_start' | 'observed_finish' }[]): AgentActivity {
  const content = object(message.content);
  const base = { activityId: message.id, kind: 'narration' as const, status: activityStatus(content.status), title: 'Observed activity' };
  if (message.activityType === 'plan' && Array.isArray(content.steps)) {
    const steps: Extract<NonNullable<AgentActivity['detail']>, { type: 'plan' }>['steps'] = content.steps.slice(0, 256).flatMap(value => {
      const step = object(value); const id = text(step.step_id, 600); const body = text(step.content);
      const status = step.status;
      return id && body && (status === 'pending' || status === 'in_progress' || status === 'completed' || status === 'cancelled') ? [{ id, content: body, status }] : [];
    });
    return { ...base, title: 'Plan', detail: { type: 'plan', steps, markers } };
  }
  if (message.activityType === 'subagent' && typeof content.invocation_id === 'string') return {
    ...base, kind: 'subagent', title: text(content.name, 256) ?? 'Delegated task',
    detail: { type: 'subagent', invocationId: content.invocation_id, ...(typeof content.tool_call_id === 'string' ? { parentToolCallId: content.tool_call_id } : {}), phase: 'delegated', timing: 'unknown' },
  };
  if (message.activityType === 'tests') return { ...base, title: 'Tests observed complete' };
  return { ...base, title: 'Unsupported activity', detail: { type: 'unsupported', reason: 'This activity requires a Host renderer. Its private payload is not displayed.' } };
}
function https(value: unknown): string | undefined {
  if (typeof value !== 'string' || value.length > 2048) return;
  try { const url = new URL(value); if (url.protocol === 'https:' && !url.username && !url.password && url.hostname !== 'localhost' && !url.hostname.endsWith('.local')) return url.href; } catch { /* unsupported */ }
}
/** Explicit whitelist preserves Artifact resolution and existing media components. */
export function contentPart(value: unknown): AgentContentPart | undefined {
  const p = object(value); const id = text(p.id, 600); const state = p.state;
  if (!id || (state !== 'processing' && state !== 'ready' && state !== 'failed')) return;
  const base: Pick<AgentContentPart, 'id' | 'state'> = { id, state };
  const title = text(p.title, 2000);
  if (p.type === 'external_video') {
    const url = https(p.sourceUrl); const posterUrl = https(p.posterUrl);
    return url && title ? { ...base, type: 'external-video', provider: videoProvider(url), url, title, ...strings(p, ['description']), ...(posterUrl ? { posterUrl } : {}) } : undefined;
  }
  if (p.type === 'chart') {
    const specArtifactId = text(p.specArtifactId, 600); const description = text(p.description, 2000);
    return title && description && specArtifactId && p.specType === 'vega-lite' && p.specVersion === '6' ? { ...base, type: 'chart', title, description, specType: 'vega-lite', specVersion: '6', specArtifactId,
      ...strings(p, ['dataArtifactId', 'fallbackImageArtifactId', 'fallbackTableArtifactId']) } : undefined;
  }
  const artifactId = text(p.artifactId, 600); const mimeType = text(p.mimeType, 256);
  if (!artifactId || !mimeType) return;
  const artifact = { ...base, artifactId, mimeType, ...strings(p, ['fileName']), ...(typeof p.sizeBytes === 'number' && Number.isFinite(p.sizeBytes) && p.sizeBytes >= 0 ? { sizeBytes: p.sizeBytes } : {}) };
  if (p.type === 'image' && typeof p.alt === 'string') return { ...artifact, ...dimensions(p), type: 'image', alt: p.alt.slice(0, 2000), ...strings(p, ['thumbnailArtifactId']) };
  if (p.type === 'video' && title) return { ...artifact, ...dimensions(p), ...(typeof p.durationMs === 'number' && Number.isSafeInteger(p.durationMs) && p.durationMs >= 0 ? { durationMs: p.durationMs } : {}), type: 'video', title, ...strings(p, ['posterArtifactId', 'captionsArtifactId', 'captionsLanguage', 'transcriptArtifactId', 'description']) };
  if (p.type === 'file' && typeof p.name === 'string') return { ...artifact, type: 'file', name: p.name.slice(0, 2000), ...strings(p, ['description']) };
}
function dimensions(source: { [key: string]: unknown }): { width?: number; height?: number } {
  const result: { width?: number; height?: number } = {};
  for (const key of ['width', 'height'] as const) {
    const value = source[key]; if (typeof value === 'number' && Number.isSafeInteger(value) && value > 0 && value <= 16384) result[key] = value;
  }
  return result;
}
function videoProvider(url: string): Extract<AgentContentPart, { type: 'external-video' }>['provider'] {
  const value = new URL(url); const host = value.hostname;
  if (['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'].includes(host)) return 'youtube';
  if (['vimeo.com', 'www.vimeo.com', 'player.vimeo.com'].includes(host)) return 'vimeo';
  if (['bilibili.com', 'www.bilibili.com', 'm.bilibili.com'].includes(host)) return 'bilibili';
  return /\.(mp4|webm)$/i.test(value.pathname) ? 'direct' : 'website';
}
function strings(source: { [key: string]: unknown }, keys: string[]): { [key: string]: string } {
  return Object.fromEntries(keys.flatMap(key => typeof source[key] === 'string' ? [[key, source[key].slice(0, 2000)]] : []));
}
export function interruptView(interrupt: Interrupt): AgentInterruptView {
  const schema = object(interrupt.responseSchema); const properties = object(schema.properties); const choice = object(properties.choice);
  const choiceObject = schema.type === 'object' && Object.keys(properties).length === 1 && Object.hasOwn(properties, 'choice');
  const values = schema.type === 'string' ? schema.enum : choiceObject ? choice.enum : undefined;
  const choices = Array.isArray(values) && values.every(value => typeof value === 'string') ? values as string[] : [];
  const kind = interrupt.reason === 'approval_required' ? 'approval' : interrupt.reason === 'clarification_required' && choices.length ? 'clarification' : 'unsupported';
  return { id: interrupt.id, kind, responseShape: choiceObject ? 'choice-object' : 'value', message: text(interrupt.message, 2000) ?? 'Input required', choices: choices.slice(0, 64), ...(interrupt.expiresAt ? { expiresAt: interrupt.expiresAt } : {}) };
}

/** Keep only the actual typed public assessment; never stringify arbitrary metadata. */
export function deliveryAssessment(value: unknown): AgentDeliveryAssessment | undefined {
  const source = object(value); const status = source.status;
  if (status !== 'complete' && status !== 'partial' && status !== 'blocked') return;
  const list = (value: unknown): readonly string[] => Array.isArray(value) ? value.slice(0, 64).flatMap(item => typeof item === 'string' ? [text(item, 2000)!] : []) : [];
  const previewTruncated = ['satisfied', 'unmet', 'evidence_refs', 'artifact_refs', 'required_outcomes'].some(key => Array.isArray(source[key]) && (source[key].length > 64 || source[key].some(item => typeof item === 'string' && item.length > 2000))) || typeof source.goal === 'string' && source.goal.length > 2000;
  const taskType = source.task_type;
  const goal = text(source.goal, 2000);
  return { status, ...(previewTruncated ? { previewTruncated: true } : {}), satisfied: list(source.satisfied), unmet: list(source.unmet), evidenceRefs: list(source.evidence_refs), artifactRefs: list(source.artifact_refs),
    ...(goal ? { goal } : {}), ...(Array.isArray(source.required_outcomes) ? { requiredOutcomes: list(source.required_outcomes) } : {}),
    ...(taskType === 'answer' || taskType === 'research' || taskType === 'change' || taskType === 'create' || taskType === 'operate' ? { taskType } : {}) };
}
