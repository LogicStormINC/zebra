import type { AgentConversationItem, AgentJsonValue, AgentDeliveryAssessment } from './index.js';

/** Display facts only; no response schema grants execution or parameter-edit authority. */
export type AgentActivityDetail =
  | { type: 'tool'; toolCallId: string; name: string; arguments: string;
      phase: 'preparing' | 'proposed' | 'executing' | 'completed' | 'failed'; result?: string }
  | { type: 'plan'; steps: readonly { id: string; content: string;
      status: 'pending' | 'in_progress' | 'completed' | 'cancelled' }[];
      markers: readonly { name: string; status: 'observed_start' | 'observed_finish' }[] }
  | { type: 'subagent'; invocationId: string; parentToolCallId?: string;
      phase: 'delegated' | 'observed' | 'completed' | 'failed' | 'cancelled' | 'suspended';
      timing: 'unknown' | 'observed_completion' | 'observed_after_execution' }
  | { type: 'unsupported'; reason: string };

export interface AgentAgUiFacts {
  execution: 'unknown' | 'running' | 'resuming' | 'waiting_input' | 'paused' | 'completed' | 'cancelled' | 'failed';
  connection: 'idle' | 'observing' | 'disconnected' | 'finished';
  submission: 'idle' | 'draft' | 'ready';
  delivery: 'unknown' | 'complete' | 'partial' | 'blocked';
  deliveryAssessment?: AgentDeliveryAssessment;
}
export interface AgentAgUiBinding { threadId: string; runId: string }
/** IDs track insertion/removal/order; snapshot identity also changes for settled message revisions.
 * Streaming updates stay entity-local. Resolve each ID through its entity selector. */
export interface AgentAgUiStructure extends AgentAgUiBinding { itemIds: readonly string[] }
export type AgentAgUiEntity = AgentConversationItem;
export type AgentInterruptResponse =
  | { interruptId: string; status: 'resolved'; payload: Exclude<AgentJsonValue, null> }
  | { interruptId: string; status: 'cancelled' };
export interface AgentInterruptView {
  id: string;
  message: string;
  kind: 'approval' | 'clarification' | 'unsupported';
  choices: readonly string[];
  responseShape?: 'value' | 'choice-object';
  expiresAt?: string;
}
/** Trusted Host-owned display ledger, stored alongside official messages/state, never authority. */
export interface AgentAgUiCheckpoint extends AgentAgUiBinding {
  version: 1;
  entities: readonly AgentAgUiEntity[];
  facts: AgentAgUiFacts;
  observationFinished: boolean;
  deliverySource?: 'answer' | 'assessment';
  argumentCompleteToolCallIds: readonly string[];
  endedMessageIds: readonly string[];
  committedMessageIds: readonly string[];
}
