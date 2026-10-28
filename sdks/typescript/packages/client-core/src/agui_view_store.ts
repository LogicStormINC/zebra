import { buildResumeArray, enforceOutgoingInput, isInterruptExpired } from '@ag-ui/client';
import type { BaseEvent, Interrupt, Message } from '@ag-ui/core';
import type { AgentActivity, AgentAgUiBinding, AgentAgUiCheckpoint, AgentAgUiEntity, AgentAgUiFacts, AgentAgUiStructure, AgentContentPart, AgentInterruptResponse, AgentInterruptView } from '@zebra-agent/ui-contracts';
import { assertAgUiBinding } from './agui_events.js';
import { copyReadableJson } from './readable_commands.js';
import { contentPart, deliveryAssessment, interruptView, object, publicActivity, publicMessage, runState, text } from './agui_view.js';

type Listener = () => void;
interface AppliedData { messages: readonly Message[]; state: unknown; pendingInterrupts?: readonly Interrupt[] }
interface Tool { name: string; arguments: string; phase: 'preparing' | 'proposed' | 'executing' | 'completed' | 'failed'; result?: string }

/** Bound display indexes over official applied data. Never applies AG-UI message/state patches. */
export class AgUiViewStore {
  readonly binding: Readonly<AgentAgUiBinding>;
  private structure: AgentAgUiStructure;
  private facts: AgentAgUiFacts = { execution: 'unknown', connection: 'idle', submission: 'idle', delivery: 'unknown' };
  private entities = new Map<string, AgentAgUiEntity>();
  private listeners = new Map<string, Set<Listener>>();
  private parents = new Map<string, string>();
  private tools = new Map<string, Tool>();
  private ends = new Set<string>();
  private argumentEnds = new Set<string>();
  private commits = new Set<string>();
  private parts = new Map<string, readonly AgentContentPart[]>();
  private dirty = new Set<string>();
  private allDirty = true;
  private replacement = false;
  private pending: readonly Interrupt[] = [];
  private interrupts: readonly AgentInterruptView[] = [];
  private responses = new Map<string, AgentInterruptResponse>();
  private markers: { name: string; status: 'observed_start' | 'observed_finish' }[] = [];
  private terminal = false;
  private deliverySource: 'answer' | 'assessment' | undefined;
  constructor(binding: AgentAgUiBinding, checkpoint?: AgentAgUiCheckpoint) {
    if (!binding.threadId || !binding.runId) throw new Error('View requires an explicit thread/run binding');
    this.binding = Object.freeze({ ...binding }); this.structure = { ...binding, itemIds: [] };
    if (checkpoint) {
      if (checkpoint.version !== 1) throw new Error('Unsupported display checkpoint version');
      assertCheckpointBudget(checkpoint);
      if (checkpoint.threadId !== binding.threadId || checkpoint.runId !== binding.runId) throw new Error('Checkpoint binding mismatch');
      this.facts = { ...checkpoint.facts, connection: 'idle', submission: 'idle' }; this.terminal = checkpoint.observationFinished; this.deliverySource = checkpoint.deliverySource;
      this.argumentEnds = new Set(checkpoint.argumentCompleteToolCallIds); this.ends = new Set(checkpoint.endedMessageIds); this.commits = new Set(checkpoint.committedMessageIds);
      for (const entity of structuredClone(checkpoint.entities)) {
        this.put(entity.id, entity);
        if (entity.kind === 'activity') for (const activity of entity.segment.activities) {
          if (activity.detail?.type === 'tool') this.tools.set(activity.detail.toolCallId, { name: activity.detail.name, arguments: activity.detail.arguments, phase: activity.detail.phase, ...(activity.detail.result !== undefined ? { result: activity.detail.result } : {}) });
          if (activity.detail?.type === 'plan') this.markers = [...activity.detail.markers];
        }
        if (entity.kind === 'message' && entity.message.parts) this.parts.set(entity.id, entity.message.parts.filter(p => p.type !== 'text'));
      }
    }
  }
  /** Persist only with the trusted official applied snapshot for this same binding. */
  checkpoint(): AgentAgUiCheckpoint {
    const checkpoint: AgentAgUiCheckpoint = { version: 1, ...this.binding, entities: this.structure.itemIds.flatMap(id => { const entity = this.entities.get(id); return entity ? [entity] : []; }), facts: this.facts, observationFinished: this.terminal, ...(this.deliverySource ? { deliverySource: this.deliverySource } : {}), argumentCompleteToolCallIds: [...this.argumentEnds], endedMessageIds: [...this.ends], committedMessageIds: [...this.commits] };
    assertCheckpointBudget(checkpoint); return structuredClone(checkpoint);
  }
  readonly getSnapshot = (): AgentAgUiStructure => this.structure;
  readonly getFacts = (): AgentAgUiFacts => this.facts;
  readonly getInterrupts = (): readonly AgentInterruptView[] => this.interrupts;
  readonly getEntity = (id: string): AgentAgUiEntity | undefined => this.entities.get(id);
  readonly getRunState = () => runState(this.facts);
  readonly subscribe = (listener: Listener) => this.listen('structure', listener);
  readonly subscribeFacts = (listener: Listener) => this.listen('facts', listener);
  readonly subscribeInterrupts = (listener: Listener) => this.listen('interrupts', listener);
  readonly subscribeEntity = (id: string, listener: Listener) => this.listen(`entity:${id}`, listener);
  private listen(key: string, listener: Listener) {
    let group = this.listeners.get(key); if (!group) this.listeners.set(key, group = new Set()); group.add(listener);
    return () => { group.delete(listener); if (!group.size) this.listeners.delete(key); };
  }
  private notify(key: string) { for (const listener of this.listeners.get(key) ?? []) listener(); }
  private updateFacts(next: Partial<AgentAgUiFacts>) {
    if (Object.entries(next).every(([key, value]) => this.facts[key as keyof AgentAgUiFacts] === value)) return;
    this.facts = { ...this.facts, ...next }; this.notify('facts');
  }
  setConnection(connection: AgentAgUiFacts['connection']) { this.updateFacts({ connection }); }
  private put(id: string, entity: AgentAgUiEntity) {
    const previous = this.entities.get(id);
    // ponytail: compare one changed entity only, never hash/dedupe event payloads or clone history.
    if (previous && JSON.stringify(previous) === JSON.stringify(entity)) return;
    this.entities.set(id, entity);
    if (!previous) { this.structure = { ...this.structure, itemIds: [...this.structure.itemIds, id] }; this.notify('structure'); }
    else if (previous.kind === 'message' && entity.kind === 'message' && entity.message.status === 'complete' &&
      (previous.message.status !== 'complete' || previous.message.content !== entity.message.content || JSON.stringify(previous.message.parts) !== JSON.stringify(entity.message.parts))) {
      // ponytail: settled revisions rebuild the Host's O(n) timeline snapshot; token updates stay entity-local.
      this.structure = { ...this.structure }; this.notify('structure');
    }
    this.notify(`entity:${id}`);
  }
  private tool(call: string) {
    const tool = this.tools.get(call); if (!tool) return;
    const activity: AgentActivity = { activityId: `tool:${call}`, kind: 'tool', title: tool.name,
      status: tool.phase === 'executing' ? 'running' : tool.phase === 'completed' || tool.phase === 'failed' ? tool.phase : 'ready',
      detail: { type: 'tool', toolCallId: call, ...tool } };
    this.put(`tool:${call}`, { id: `tool:${call}`, kind: 'activity', segment: { id: `tool:${call}`, activities: [activity] } });
  }
  private activity(value: AgentActivity, id = `activity:${value.activityId}`) { this.put(id, { id, kind: 'activity', segment: { id: value.activityId, activities: [value] } }); }
  /** Pass only normalized, binding-checked events from G3 onEvent. Hints are display-only. */
  onEvent(event: BaseEvent): void {
    assertAgUiBinding({ threadId: typeof event.threadId === 'string' ? event.threadId : undefined, runId: typeof event.runId === 'string' ? event.runId : undefined }, this.binding);
    const messageId = typeof event.messageId === 'string' ? event.messageId : undefined; if (messageId) this.dirty.add(messageId);
    if (event.type === 'RUN_STARTED') this.setConnection('observing');
    if (event.type === 'RUN_FINISHED' || event.type === 'RUN_ERROR') { this.terminal = true; this.setConnection('finished'); }
    if (event.type === 'MESSAGES_SNAPSHOT') { this.allDirty = true; this.replacement = true; }
    if (event.type === 'TEXT_MESSAGE_END' && messageId) {
      this.ends.add(messageId);
      const entity = this.entities.get(`message:${messageId}`);
      if (entity?.kind === 'message') this.put(entity.id, { ...entity, message: { ...entity.message, status: 'complete', ...(entity.message.parts ? { parts: entity.message.parts.map(part => part.type === 'text' ? { ...part, state: 'ready' } : part) } : {}) } });
    }
    const call = typeof event.toolCallId === 'string' ? event.toolCallId : undefined;
    if (event.type === 'TOOL_CALL_START' && call) {
      // Pinned official 1.0.3 uses the call ID for an omitted assistant parent.
      const parent = typeof event.parentMessageId === 'string' ? event.parentMessageId : call; this.parents.set(call, parent);
      this.tools.set(call, { name: text(event.toolCallName, 256) ?? 'Tool', arguments: '', phase: 'preparing' });
    }
    if (call) { const parent = this.parents.get(call); if (parent) this.dirty.add(parent); }
    if (event.type === 'TOOL_CALL_END' && call) { this.argumentEnds.add(call); const tool = this.tools.get(call); if (tool && tool.phase === 'preparing') { tool.phase = 'proposed'; this.tool(call); } }
    if ((event.type === 'STEP_STARTED' || event.type === 'STEP_FINISHED') && !event.subagentRunId) {
      for (const [id, entity] of this.entities) if (entity.kind === 'activity' && entity.segment.activities[0]?.detail?.type === 'plan') this.dirty.add(entity.segment.activities[0]!.activityId);
      const name = text(event.stepName, 600); if (name) this.markers = [...this.markers.slice(-255), { name, status: event.type === 'STEP_STARTED' ? 'observed_start' : 'observed_finish' }];
    }
    const child = typeof event.subagentRunId === 'string' ? event.subagentRunId : undefined;
    if (child && ['SUBAGENT_STARTED', 'SUBAGENT_FINISHED', 'SUBAGENT_ERROR'].includes(event.type)) {
      const old = this.entities.get(`child:${child}`); const previous = old?.kind === 'activity' ? old.segment.activities[0]?.detail : undefined;
      const timing = object(object(event.metadata).zebra).timing;
      const parent = (typeof event.parentToolCallId === 'string' ? event.parentToolCallId : undefined) ?? (previous?.type === 'subagent' ? previous.parentToolCallId : undefined);
      const code = text(event.code);
      const phase = event.type === 'SUBAGENT_STARTED' ? 'observed' : event.type === 'SUBAGENT_ERROR' ? (code === 'zebra_child_cancelled' || code === 'subagent_cancelled') ? 'cancelled' : 'failed' : object(event.outcome).type === 'suspended' ? 'suspended' : 'completed';
      this.activity({ activityId: child, kind: 'subagent', title: text(event.name, 256) ?? (old?.kind === 'activity' ? old.segment.activities[0]?.title : undefined) ?? 'Child execution',
        status: phase === 'completed' || phase === 'failed' || phase === 'cancelled' ? phase : 'ready', detail: { type: 'subagent', invocationId: child, ...(parent ? { parentToolCallId: parent } : {}), phase,
          timing: timing === 'observed_completion' || timing === 'observed_after_execution' ? timing : previous?.type === 'subagent' ? previous.timing : 'unknown' } }, `child:${child}`);
    }
    if (event.type === 'CUSTOM') {
      const value = object(event.value);
      if (event.name === 'zebra.answer_committed.v1' && typeof value.message_id === 'string') {
        this.deliverySource = 'answer'; this.commits.add(value.message_id); this.dirty.add(value.message_id);
        const entity = this.entities.get(`message:${value.message_id}`);
        if (entity?.kind === 'message') this.put(entity.id, { ...entity, message: { ...entity.message, presentation: 'committed' } });
        const assessment = deliveryAssessment(value.delivery_assessment);
        const status = value.delivery_status; if (status === 'complete' || status === 'partial' || status === 'blocked') this.updateFacts({ delivery: status, ...(assessment ? { deliveryAssessment: assessment } : {}) });
      } else if (event.name === 'zebra.delivery_assessment.v1') {
        const assessment = deliveryAssessment(value); if (assessment) this.deliverySource = 'assessment'; if (assessment) this.updateFacts({ delivery: assessment.status, deliveryAssessment: assessment });
      } else if (event.name === 'zebra.content_part') {
        const part = contentPart(value.part); const call = typeof value.tool_call_id === 'string' ? value.tool_call_id : undefined;
        if (part && call) {
          const id = `media:${call}`; const previous = this.parts.get(id) ?? [];
          if (previous.length >= 8 && !previous.some(p => p.id === part.id)) { this.unsupported('content', 'Additional media parts exceed the display bound. A Host renderer is required.'); return; }
          this.parts.set(id, previous.some(p => p.id === part.id) ? previous.map(p => p.id === part.id ? part : p) : [...previous, part]);
          this.put(id, { id, kind: 'message', message: { id, role: 'assistant', content: '', status: 'complete', parts: this.parts.get(id)! } });
        } else this.unsupported('content', 'A supplied file or media part could not be displayed. A Host renderer is required.');
      } else if (!['zebra.model_usage.v1'].includes(String(event.name))) this.unsupported('extension', 'Unsupported extension. A Host renderer may be required.');
    }
    // RAW/encrypted/reasoning payloads are deliberately never text/HTML/JS.
  }
  private unsupported(id: string, reason: string) { this.activity({ activityId: `unsupported:${id}`, kind: 'narration', status: 'blocked', title: 'Unsupported public content', detail: { type: 'unsupported', reason } }, `unsupported:${id}`); }
  /** Called after official application/drain (Http onApplied or recorded onSnapshot). */
  apply(data: AppliedData & Partial<AgentAgUiBinding>): void {
    assertAgUiBinding(data, this.binding);
    const replacement = this.replacement;
    if (replacement) {
      const messages = new Set(data.messages.map(message => message.id));
      const calls = new Set(data.messages.flatMap(message => message.role === 'assistant' ? (message.toolCalls ?? []).map(call => call.id) : []));
      const mediaIds = new Set([...calls].map(call => `media:${call}`));
      for (const [id, entity] of this.entities) {
        const keep = entity.kind === 'message' ? entity.id.startsWith('media:') ? mediaIds.has(entity.id) : messages.has(entity.message.id)
          : entity.kind === 'activity' && entity.segment.activities.some(activity => messages.has(activity.activityId) || activity.detail?.type === 'tool' && calls.has(activity.detail.toolCallId));
        if (!keep) { this.entities.delete(id); this.notify(`entity:${id}`); }
      }
      const itemIds = this.structure.itemIds.filter(id => this.entities.has(id));
      if (itemIds.length !== this.structure.itemIds.length) { this.structure = { ...this.structure, itemIds }; this.notify('structure'); }
      this.ends = new Set([...this.ends].filter(id => messages.has(id))); this.commits = new Set([...this.commits].filter(id => messages.has(id)));
      // The replacing official document is the source for tool execution/result facts.
      this.tools.clear(); this.parents.clear(); this.argumentEnds = new Set([...this.argumentEnds].filter(call => calls.has(call)));
      for (const id of this.parts.keys()) if (!this.entities.has(id)) this.parts.delete(id);
      if (!this.commits.size && this.deliverySource === 'answer') { const { deliveryAssessment: _old, ...facts } = this.facts; this.facts = { ...facts, delivery: 'unknown' }; this.notify('facts'); }
      this.replacement = false;
    }
    const status = object(object(data.state).execution).status;
    if (status === 'running' || status === 'resuming' || status === 'waiting_input' || status === 'paused' || status === 'completed' || status === 'cancelled' || status === 'failed') this.updateFacts({ execution: status });
    else this.updateFacts({ execution: 'unknown' });
    const selected = this.allDirty ? data.messages : [...this.dirty].flatMap(id => { const message = data.messages.find(m => m.id === id); return message ? [message] : []; });
    // ponytail: official data exposes arrays; targeted lookups are O(n), upgrade to an upstream entity index if needed.
    for (const message of selected) {
      if (message.role === 'assistant' && !message.subagentRunId) for (const call of message.toolCalls ?? []) {
          this.parents.set(call.id, message.id);
          const previous = this.tools.get(call.id);
          this.tools.set(call.id, { name: text(call.function.name, 256) ?? 'Tool', arguments: text(call.function.arguments) ?? '', phase: previous?.phase ?? (this.argumentEnds.has(call.id) ? 'proposed' : 'preparing'), ...(previous?.result !== undefined ? { result: previous.result } : {}) }); this.tool(call.id);
        }
    }
    for (const message of selected) {
      if (Array.isArray(message.content)) this.unsupported('multimodal', 'This message contains unsupported structured content. A Host renderer is required.');
      if (message.subagentRunId) { this.unsupported('child-content', 'Child content requires an invocation-scoped Host renderer.'); continue; }
      if (message.role === 'activity') {
        const content = object(message.content); const call = typeof content.tool_call_id === 'string' ? content.tool_call_id : undefined;
        if (message.activityType === 'tool_execution' && call) {
          const tool = this.tools.get(call);
          if (tool && (content.status === 'running' || content.status === 'completed' || content.status === 'failed')) { tool.phase = content.status === 'running' ? 'executing' : content.status; this.tool(call); }
          else this.unsupported('tool', 'Execution observed without a bound proposal.');
        } else {
          const activity = publicActivity(message, this.markers); const id = activity.detail?.type === 'subagent' ? `child:${activity.detail.invocationId}` : `activity:${activity.activityId}`; const previous = this.entities.get(id);
          if (activity.detail?.type === 'subagent' && previous?.kind === 'activity' && previous.segment.activities[0]?.detail?.type === 'subagent') continue;
          this.activity(activity, id);
        }
      } else if (message.role === 'tool') {
        const tool = this.tools.get(message.toolCallId);
        if (tool) { tool.result = text(message.content) ?? ''; this.tool(message.toolCallId); }
        else this.activity({ activityId: message.id, kind: 'tool', title: 'Unbound tool result', status: 'ready', description: text(message.content) ?? 'Unsupported result content', detail: { type: 'unsupported', reason: 'No bound proposal is available. Execution state is unknown.' } }, `result:${message.id}`);
      } else {
        const output = publicMessage(message, this.commits.has(message.id), this.ends.has(message.id), this.parts.get(`message:${message.id}`) ?? []);
        if (output) this.put(`message:${message.id}`, { id: `message:${message.id}`, kind: 'message', message: output });
      }
    }
    if (this.allDirty || replacement) this.reorder(data.messages);
    this.dirty.clear(); this.allDirty = false;
    const pending = data.pendingInterrupts ?? [];
    if (JSON.stringify(pending) !== JSON.stringify(this.pending)) {
      this.pending = structuredClone(pending); this.interrupts = pending.map(interruptView); this.responses.clear(); this.updateFacts({ submission: 'idle' }); this.notify('interrupts');
    }
  }
  private reorder(messages: readonly Message[]): void {
    const itemIds: string[] = []; const seen = new Set<string>(); const attached = new Map<string, string[]>();
    for (const id of this.structure.itemIds) {
      const entity = this.entities.get(id); const detail = entity?.kind === 'activity' ? entity.segment.activities[0]?.detail : undefined;
      const call = entity?.kind === 'message' && entity.id.startsWith('media:') ? entity.id.slice(6) : detail?.type === 'subagent' ? detail.parentToolCallId : undefined;
      if (call) { const key = `tool:${call}`; attached.set(key, [...(attached.get(key) ?? []), id]); }
    }
    const add = (id: string) => { if (!seen.has(id) && this.entities.has(id)) { seen.add(id); itemIds.push(id); } };
    const row = (id: string) => { add(id); for (const child of attached.get(id) ?? []) add(child); };
    for (const message of messages) {
      if (message.role === 'activity') row(message.activityType === 'tool_execution' && typeof object(message.content).tool_call_id === 'string' ? `tool:${object(message.content).tool_call_id}` : message.activityType === 'subagent' && typeof object(message.content).invocation_id === 'string' ? `child:${object(message.content).invocation_id}` : `activity:${message.id}`);
      else if (message.role === 'tool') row(this.tools.has(message.toolCallId) ? `tool:${message.toolCallId}` : `result:${message.id}`);
      else { row(`message:${message.id}`); if (message.role === 'assistant') for (const call of message.toolCalls ?? []) row(`tool:${call.id}`); }
    }
    for (const id of this.structure.itemIds) add(id);
    if (itemIds.some((id, index) => id !== this.structure.itemIds[index])) { this.structure = { ...this.structure, itemIds }; this.notify('structure'); }
  }
  setResponse(binding: AgentAgUiBinding, response: AgentInterruptResponse): void {
    assertAgUiBinding(binding, this.binding);
    if (binding.threadId !== this.binding.threadId || binding.runId !== this.binding.runId || !this.pending.some(i => i.id === response.interruptId)) throw new Error('Unknown or old interrupt binding');
    if (response.status === 'resolved') copyReadableJson({ payload: response.payload });
    this.responses.set(response.interruptId, structuredClone(response)); this.updateFacts({ submission: 'draft' });
  }
  /** Returns a complete local draft only. Host/G5 still owns current authority and HTTP submission. */
  prepareResponses(binding: AgentAgUiBinding, entries: readonly AgentInterruptResponse[] = [...this.responses.values()], now = new Date()): readonly AgentInterruptResponse[] {
    assertAgUiBinding(binding, this.binding);
    if (binding.threadId !== this.binding.threadId || binding.runId !== this.binding.runId || !this.terminal || !this.pending.length || !Number.isFinite(now.getTime())) throw new Error('No current interrupted Run');
    if (new Set(this.pending.map(i => i.id)).size !== this.pending.length || new Set(entries.map(e => e.interruptId)).size !== entries.length) throw new Error('Duplicate interrupt');
    const responses: Parameters<typeof buildResumeArray>[1] = Object.create(null);
    for (const entry of entries) {
      if (entry.status === 'resolved') { if (entry.payload === null || entry.payload === undefined) throw new Error('Resolved payload requires non-null JSON'); copyReadableJson({ payload: entry.payload }); }
      const { interruptId, ...response } = entry; responses[interruptId] = response;
    }
    const resume = buildResumeArray([...this.pending], responses);
    for (const interrupt of this.pending) if (responses[interrupt.id]?.status !== 'cancelled' && (isInterruptExpired(interrupt, now) || interrupt.expiresAt !== undefined && !Number.isFinite(Date.parse(interrupt.expiresAt)))) throw new Error('Interrupt expired; explicit cancellation is available');
    enforceOutgoingInput({ ...this.binding, protocolVersion: '1.0', messages: [], state: {}, tools: [], context: [], forwardedProps: {}, resume });
    this.updateFacts({ submission: 'ready' }); return structuredClone(resume) as readonly AgentInterruptResponse[];
  }
}

function assertCheckpointBudget(checkpoint: AgentAgUiCheckpoint): void {
  if (checkpoint.entities.length > 4096 || checkpoint.argumentCompleteToolCallIds.length > 4096 || checkpoint.endedMessageIds.length > 4096 || checkpoint.committedMessageIds.length > 4096 || new TextEncoder().encode(JSON.stringify(checkpoint)).byteLength > 2_097_152) throw new Error('Display checkpoint exceeds budget');
}
