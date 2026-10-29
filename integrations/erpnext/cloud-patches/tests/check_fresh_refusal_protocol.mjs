import assert from 'node:assert/strict';
import { reduceEvent } from '../host-overrides/frontend/protocol.mjs';
const before = { messages: [{ id: 'human', role: 'user', content: 'request' }], status: 'running', canonical_status: 'ready', activities: [], content_parts: [] };
for (const code of ['erp_fresh_authority_refused', 'erp_fresh_authority_unavailable', 'erp_fresh_authority_retry_exhausted']) {
  const state = reduceEvent(before, { type: 'CUSTOM', name: 'zebra.observation.problem', value: { code } });
  assert.equal(state.messages, before.messages);
  assert.equal(state.canonical_status, 'ready');
  assert.equal(state.status, code === 'erp_fresh_authority_unavailable' ? 'waiting' : 'blocked');
  assert.deepEqual(state.run_state.availableActions, []); // Snapshot proof owns the explicit action.
}
const unknown = reduceEvent(before, { type: 'CUSTOM', name: 'zebra.observation.problem', value: { code: 'untrusted_refusal' } });
assert.equal(unknown.status, 'running');
assert.deepEqual(unknown.messages, before.messages);
assert.deepEqual(unknown.run_state, { phase: 'running', availableActions: [] });
console.log('PASS fixed fresh observation metadata preserves messages/canonical status and cannot grant retry without authorized snapshot');
