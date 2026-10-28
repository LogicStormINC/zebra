'use client';
import React, { memo, useCallback, useEffect, useId, useMemo, useState, type ReactNode } from 'react';
import type { AgUiViewStore } from '@zebra-agent/client-core';
import type { AgentAgUiBinding, AgentAgUiFacts, AgentConversationItem, AgentConversationTurn, AgentInterruptResponse, AgentInterruptView } from '@zebra-agent/ui-contracts';
import { useAgUiEntity, useAgUiFacts, useAgUiInterrupts, useAgUiView } from '../agui_view.ts';
import { AgentConversationTimeline, type AgentConversationTimelineProps } from './agent-conversation-timeline.tsx';
import { AgentMessageItem, resolveAgentMessageLabels } from './agent-message-list.tsx';
import { AgentActivityGroup } from './agent-activity-group.tsx';
import { AgentRunStatus } from './agent-run-status.tsx';

export interface AgentAgUiConversationProps {
  store: AgUiViewStore;
  contentRenderer?: AgentConversationTimelineProps['contentRenderer'];
  /** Local complete draft only; this callback is not Native decision/effect authority. */
  onDraft?: (binding: AgentAgUiBinding, entries: readonly AgentInterruptResponse[]) => void;
  renderUnsupportedInterrupt?: (interrupt: AgentInterruptView, setResponse: (response: AgentInterruptResponse) => void) => ReactNode;
}
/** Minimal Host bridge: wire store.onEvent/onApplied into the official G3 client. */
export function AgentAgUiConversation(props: AgentAgUiConversationProps) {
  const structure = useAgUiView(props.store); const facts = useAgUiFacts(props.store);
  const turns = useMemo<readonly AgentConversationTurn[]>(() => [{ id: JSON.stringify([structure.threadId, structure.runId]),
    status: turnStatus(facts.execution), workSegments: [], items: structure.itemIds.flatMap(id => { const item = props.store.getEntity(id); return item ? [item.kind === 'message' ? { ...item, message: { ...item.message, id: item.id } } : item] : []; }) }], [structure, facts.execution, props.store]);
  const renderItem = useCallback((item: AgentConversationItem) => <EntityRow store={props.store} id={item.id} contentRenderer={props.contentRenderer} />, [props.store, props.contentRenderer]);
  return <>
    <AgentConversationTimeline turns={turns} scrollKey={JSON.stringify(props.store.binding)} renderItem={renderItem} />
    <ViewStatus store={props.store} />
    <InterruptDraft key={JSON.stringify(props.store.binding)} {...props} />
  </>;
}
const EntityRow = memo(function EntityRow({ store, id, contentRenderer }: { store: AgUiViewStore; id: string; contentRenderer: AgentConversationTimelineProps['contentRenderer'] }) {
  const entity = useAgUiEntity(store, id); const [expanded, setExpanded] = useState(false);
  if (!entity) return null;
  if (entity.kind === 'message') return <ol className="zebra-agent-message-list zebra-agent-turn__messages"><AgentMessageItem message={entity.message} labels={resolveAgentMessageLabels()} contentRenderer={contentRenderer} /></ol>;
  if (entity.kind === 'activity') return <AgentActivityGroup activities={entity.segment.activities} expanded={expanded} onExpandedChange={setExpanded} />;
  return <AgentRunStatus state={entity.state} />;
});
function ViewStatus({ store }: { store: AgUiViewStore }) {
  const facts = useAgUiFacts(store);
  return <div><AgentRunStatus state={store.getRunState()} />
    <span role="status" aria-live="polite">Observation: {facts.connection} · Delivery: {facts.delivery} · Local response: {facts.submission}</span>
    {facts.deliveryAssessment ? <details><summary>Delivery assessment · {facts.deliveryAssessment.status}</summary>
      {facts.deliveryAssessment.previewTruncated ? <p>This bounded preview omits additional assessment details. The Host retains the full assessment.</p> : null}
      {facts.deliveryAssessment.goal ? <p>{facts.deliveryAssessment.goal}</p> : null}
      {facts.deliveryAssessment.satisfied.length ? <><strong>Satisfied</strong><ul>{facts.deliveryAssessment.satisfied.map((item, index) => <li key={index}>{item}</li>)}</ul></> : null}
      {facts.deliveryAssessment.unmet.length ? <><strong>Unmet requirements</strong><ul>{facts.deliveryAssessment.unmet.map((item, index) => <li key={index}>{item}</li>)}</ul></> : null}
      {facts.deliveryAssessment.requiredOutcomes?.length ? <><strong>Required outcomes</strong><ul>{facts.deliveryAssessment.requiredOutcomes.map((item, index) => <li key={index}>{item}</li>)}</ul></> : null}
    </details> : null}</div>;
}
// Waiting is a structural slot; ViewStatus retains the actual paused execution fact.
function turnStatus(execution: AgentAgUiFacts['execution']): AgentConversationTurn['status'] {
  return execution === 'completed' || execution === 'cancelled' || execution === 'failed' ? execution : execution === 'paused' ? 'waiting' : execution === 'waiting_input' ? 'waiting' : execution === 'unknown' ? 'queued' : 'running';
}
function InterruptDraft({ store, onDraft, renderUnsupportedInterrupt }: AgentAgUiConversationProps) {
  const interrupts = useAgUiInterrupts(store); const id = useId();
  const [selected, setSelected] = useState<{ [id: string]: string }>({}); const [error, setError] = useState('');
  useEffect(() => { setSelected({}); setError(''); }, [interrupts, store]);
  const setResponse = (response: AgentInterruptResponse, label: string) => {
    store.setResponse(store.binding, response); setSelected(previous => ({ ...previous, [response.interruptId]: label })); setError('');
  };
  if (!interrupts.length) return null;
  return <section className="zebra-agent-interrupt" aria-labelledby={`${id}-heading`}>
    <h3 id={`${id}-heading`}>Pending input · local draft</h3>
    {interrupts.map((interrupt, index) => {
      const expires = interrupt.expiresAt === undefined ? undefined : Date.parse(interrupt.expiresAt);
      const expired = expires !== undefined && (!Number.isFinite(expires) || expires <= Date.now());
      const choices = interrupt.kind === 'approval' ? ['approve', 'reject'] : interrupt.choices;
      return <fieldset key={`${interrupt.id}:${index}`}><legend>{interrupt.message}</legend>
        {expired ? <p>Expired input can be explicitly cancelled.</p> : null}
        {interrupt.kind === 'unsupported' ? renderUnsupportedInterrupt?.(interrupt, response => setResponse(response, response.status)) ?? <p>This input requires a Host renderer. The supplied schema does not grant editing permission.</p> : choices.map(choice => <button
          type="button" key={choice} disabled={expired} aria-pressed={selected[interrupt.id] === choice}
          onClick={() => setResponse({ interruptId: interrupt.id, status: 'resolved', payload: interrupt.kind === 'approval' ? { decision: choice } : interrupt.responseShape === 'choice-object' ? { choice } : choice }, choice)}>{choice === 'approve' ? 'Approve' : choice === 'reject' ? 'Reject' : choice}</button>)}
        <button type="button" aria-pressed={selected[interrupt.id] === 'cancelled'} onClick={() => setResponse({ interruptId: interrupt.id, status: 'cancelled' }, 'cancelled')}>Cancel input</button>
        <span id={`${id}-selection-${index}`} role="status">{selected[interrupt.id] ?? 'No local response selected'}</span>
      </fieldset>;
    })}
    <button type="button" disabled={!onDraft} onClick={() => {
      try { const entries = store.prepareResponses(store.binding); setError(''); onDraft?.(store.binding, entries); }
      catch { setError('Complete every current input with a valid response or explicit cancellation. Expired inputs must be cancelled.'); }
    }}>Prepare complete response set</button>
    {error ? <p role="alert">{error}</p> : null}
  </section>;
}
