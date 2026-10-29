import assert from 'node:assert/strict';
import test from 'node:test';
import { StandardAgUiConsumer } from '../src/agui_reducer.ts';
import { AgUiViewStore } from '../src/agui_view_store.ts';
const binding = { threadId: 'thread', runId: 'run' };
const start = { type: 'RUN_STARTED', ...binding };
const finish = { type: 'RUN_FINISHED', ...binding };
function setup() {
  const store = new AgUiViewStore(binding);
  const consumer = new StandardAgUiConsumer(binding, { onEvent: event => store.onEvent(event), onSnapshot: value => store.apply(value) });
  return { store, consumer };
}
test('official applied data distinguishes complete arguments from execution and committed delivery', async () => {
  const { store, consumer } = setup();
  const stages: string[] = [];
  store.subscribeEntity('tool:t', () => { const row = store.getEntity('tool:t'); if (row?.kind === 'activity') stages.push(row.segment.activities[0]!.detail!.type === 'tool' ? row.segment.activities[0]!.detail!.phase : 'wrong'); });
  await consumer.consume([start,
    { type: 'TOOL_CALL_START', toolCallId: 't', toolCallName: 'shell', parentMessageId: 'proposal' },
    { type: 'TOOL_CALL_ARGS', toolCallId: 't', delta: '{}' }, { type: 'TOOL_CALL_END', toolCallId: 't' },
    { type: 'ACTIVITY_SNAPSHOT', messageId: 'execution:t', activityType: 'tool_execution', content: { tool_call_id: 't', status: 'running' } },
    { type: 'ACTIVITY_SNAPSHOT', messageId: 'execution:t', activityType: 'tool_execution', content: { tool_call_id: 't', status: 'completed' } },
    { type: 'TOOL_CALL_RESULT', toolCallId: 't', messageId: 'result', content: 'done', role: 'tool' },
    { type: 'TEXT_MESSAGE_CHUNK', messageId: 'answer', role: 'assistant', delta: 'hello' }, finish]);
  assert.ok(stages.includes('proposed')); assert.ok(stages.includes('executing')); assert.equal(stages.at(-1), 'completed');
  assert.equal(store.getFacts().delivery, 'unknown');
  assert.equal(store.getFacts().execution, 'unknown');
  assert.equal(store.getEntity('message:answer')?.kind, 'message');
});
test('source execution wins over protocol completion and connection is independent', async () => {
  const { store, consumer } = setup();
  await consumer.consume([start, { type: 'STATE_SNAPSHOT', snapshot: { execution: { status: 'paused' } } }, finish]);
  store.setConnection('disconnected');
  assert.equal(store.getFacts().execution, 'paused');
  assert.equal(store.getFacts().connection, 'disconnected');
  assert.deepEqual(store.getRunState().availableActions, []);
});
test('1/3/12 scoped consumers preserve unrelated entities and structure during 100 identical deltas', async () => {
  for (const count of [1, 3, 12]) {
    const pairs = Array.from({ length: count }, (_, index) => {
      const binding = { threadId: `t${index}`, runId: `r${index}` }; const store = new AgUiViewStore(binding);
      return { store, consumer: new StandardAgUiConsumer(binding, { onEvent: e => store.onEvent(e), onSnapshot: s => store.apply(s) }), binding };
    });
    for (const pair of pairs) {
      const { store, consumer, binding: b } = pair;
      let peerNotifications = 0;
      const unsubscribes = pairs.filter(p => p !== pair).map(p => p.store.subscribe(() => peerNotifications++));
      async function* source() {
        yield { type: 'RUN_STARTED', ...b };
        yield { type: 'TEXT_MESSAGE_CHUNK', messageId: 'one', role: 'assistant', delta: `first-${b.runId}` };
        yield { type: 'TEXT_MESSAGE_START', messageId: 'two', role: 'assistant' };
        yield { type: 'TEXT_MESSAGE_CONTENT', messageId: 'two', delta: 'a' };
        const first = store.getEntity('message:one'); const structure = store.getSnapshot();
        let unchangedNotifications = 0; const unsubscribe = store.subscribeEntity('message:one', () => unchangedNotifications++);
        for (let index = 0; index < 99; index++) {
          yield { type: 'TEXT_MESSAGE_CONTENT', messageId: 'two', delta: 'a' };
          assert.equal(store.getEntity('message:one'), first); assert.equal(store.getSnapshot(), structure);
        }
        assert.equal(unchangedNotifications, 0); unsubscribe();
        yield { type: 'TEXT_MESSAGE_END', messageId: 'two' }; yield { type: 'RUN_FINISHED', ...b };
      }
      await consumer.consume(source());
      assert.equal(peerNotifications, 0); unsubscribes.forEach(unsubscribe => unsubscribe());
      const two = store.getEntity('message:two'); assert.equal(two?.kind === 'message' && two.message.content, 'a'.repeat(100));
    }
  }
});

test('complete local interrupt set rejects stale, missing, duplicate, expired and non-JSON responses', async () => {
  const { store, consumer } = setup();
  await consumer.consume([start, { ...finish, outcome: { type: 'interrupt', interrupts: [
    { id: 'a', reason: 'approval_required' }, { id: 'b', reason: 'clarification_required', expiresAt: '2000-01-01T00:00:00Z' },
  ] } }]);
  const a = { interruptId: 'a', status: 'resolved' as const, payload: false };
  const b = { interruptId: 'b', status: 'cancelled' as const };
  assert.throws(() => store.prepareResponses({ ...binding, runId: 'old' }, [a, b]));
  assert.throws(() => store.prepareResponses(binding, [a]), /missing/);
  assert.throws(() => store.prepareResponses(binding, [a, a]), /Duplicate/);
  assert.throws(() => store.prepareResponses(binding, [a, { interruptId: 'b', status: 'resolved', payload: true }]), /expired/);
  assert.throws(() => store.prepareResponses(binding, [a, b, { interruptId: 'old', status: 'cancelled' }]), /unknown/);
  assert.throws(() => store.setResponse(binding, { interruptId: 'a', status: 'resolved', payload: new Date() as never }));
  assert.deepEqual(store.prepareResponses(binding, [a, b]), [a, b]);
});

test('snapshot replacement removes stale rows and conservative restoration does not invent delivery', async () => {
  const { store, consumer } = setup();
  await consumer.consume([start, { type: 'TEXT_MESSAGE_CHUNK', messageId: 'old', role: 'assistant', delta: 'old' },
    { type: 'MESSAGES_SNAPSHOT', messages: [{ id: 'new', role: 'user', content: 'new' }] }, finish]);
  assert.equal(store.getEntity('message:old'), undefined);
  assert.deepEqual(store.getSnapshot().itemIds, ['message:new']);
  const cold = new AgUiViewStore(binding); cold.apply(consumer.snapshot);
  assert.equal(cold.getFacts().delivery, 'unknown'); assert.equal(cold.getFacts().execution, 'unknown');
});

test('plans and exact child invocations show observed facts without fabricated timing or parent settlement', async () => {
  const { store, consumer } = setup();
  await consumer.consume([start,
    { type: 'ACTIVITY_SNAPSHOT', messageId: 'plan', activityType: 'plan', content: { steps: [{ step_id: 's', content: 'real plan', status: 'completed' }] } },
    { type: 'STEP_STARTED', stepName: 's:epoch' }, { type: 'STEP_FINISHED', stepName: 's:epoch' },
    { type: 'ACTIVITY_SNAPSHOT', messageId: 'delegation:one', activityType: 'subagent', content: { invocation_id: 'delegation:one', tool_call_id: 't', name: 'Child one', status: 'delegated' } },
    { type: 'ACTIVITY_SNAPSHOT', messageId: 'delegation:two', activityType: 'subagent', content: { invocation_id: 'delegation:two', tool_call_id: 't', name: 'Child two', status: 'delegated' } },
    { type: 'SUBAGENT_STARTED', subagentRunId: 'delegation:one', parentToolCallId: 't', name: 'Child one', metadata: { zebra: { timing: 'observed_completion' } } },
    { type: 'SUBAGENT_FINISHED', subagentRunId: 'delegation:one' },
    { type: 'STATE_SNAPSHOT', snapshot: { execution: { status: 'cancelled' } } }, { ...finish, outcome: { type: 'cancelled' } }]);
  const one = store.getEntity('child:delegation:one'); const two = store.getEntity('child:delegation:two'); const plan = store.getEntity('activity:plan');
  assert.equal(one?.kind === 'activity' && one.segment.activities[0]?.detail?.type === 'subagent' && one.segment.activities[0].detail.phase, 'completed');
  assert.equal(two?.kind === 'activity' && two.segment.activities[0]?.detail?.type === 'subagent' && two.segment.activities[0].detail.phase, 'delegated');
  assert.equal(plan?.kind === 'activity' && plan.segment.activities[0]?.detail?.type === 'plan' && plan.segment.activities[0].detail.markers.length, 2);
  assert.equal(one?.kind === 'activity' && one.segment.activities[0]?.durationMs, undefined);
});

test('actual Python producer -> official consumer -> cold view checkpoint preserves public facts/media identities', async () => {
  const { producerRecording } = await import('./agui-view-fixture.ts');
  const recording = producerRecording(); const b = { threadId: 'task', runId: 'public-run' };
  const store = new AgUiViewStore(b); const consumer = new StandardAgUiConsumer(b, { onEvent: e => store.onEvent(e), onSnapshot: s => store.apply(s) });
  await consumer.consume(recording);
  assert.equal(store.getFacts().execution, 'completed'); assert.equal(store.getFacts().delivery, 'complete');
  assert.ok(store.getSnapshot().itemIds.includes('media:t'));
  const media = store.getEntity('media:t');
  assert.equal(media?.kind, 'message');
  if (media?.kind !== 'message') throw new Error('missing media');
  const image = media.message.parts?.find(p => p.type === 'image');
  const video = media.message.parts?.find(p => p.type === 'video');
  const external = media.message.parts?.find(p => p.type === 'external-video');
  const chart = media.message.parts?.find(p => p.type === 'chart');
  assert.equal(image?.width, 640); assert.equal(image?.height, 480);
  assert.equal(video?.durationMs, 1234); assert.equal(video?.width, 1280); assert.equal(video?.captionsLanguage, 'en');
  assert.equal(external?.description, 'Public source video'); assert.equal(external?.provider, 'youtube');
  assert.equal(chart?.fallbackImageArtifactId, '00000000-0000-4000-8000-000000000003');
  const saved = consumer.snapshot; const checkpoint = store.checkpoint();
  const cold = new AgUiViewStore(b, checkpoint);
  cold.apply(saved);
  assert.deepEqual(cold.checkpoint().entities, checkpoint.entities);
  assert.equal(cold.getFacts().delivery, 'complete');
  assert.throws(() => new AgUiViewStore({ ...b, runId: 'old' }, checkpoint), /binding/);
});

test('replacement retaining a tool keeps its bound media/commit ledger; removal cannot revive them', async () => {
  const { producerRecording } = await import('./agui-view-fixture.ts');
  const b = { threadId: 'task', runId: 'public-run' }; const store = new AgUiViewStore(b);
  const consumer = new StandardAgUiConsumer(b, { onEvent: e => store.onEvent(e), onSnapshot: s => store.apply(s) });
  await consumer.consume(producerRecording());
  const saved = consumer.snapshot; const media = store.getEntity('media:t');
  store.onEvent({ type: 'MESSAGES_SNAPSHOT', messages: saved.messages } as never); store.apply(saved);
  assert.equal(store.getEntity('media:t'), media); assert.equal(store.getFacts().delivery, 'complete');
  store.onEvent({ type: 'MESSAGES_SNAPSHOT', messages: [] } as never); store.apply({ ...saved, messages: [] });
  assert.equal(store.getEntity('media:t'), undefined); assert.equal(store.getFacts().delivery, 'unknown');
  assert.deepEqual(store.getSnapshot().itemIds, []);
});

test('removed source execution becomes unknown, and media revisions preserve slots with explicit bounds', () => {
  const store = new AgUiViewStore(binding);
  store.apply({ messages: [], state: { execution: { status: 'completed' } } });
  store.apply({ messages: [], state: {} }); assert.equal(store.getFacts().execution, 'unknown');
  const add = (index: number, name = `file-${index}`) => store.onEvent({ type: 'CUSTOM', name: 'zebra.content_part', value: { tool_call_id: 't', part: { id: `p${index}`, type: 'file', state: 'ready', artifactId: `artifact-${index}`, mimeType: 'text/plain', name } } } as never);
  add(1); add(2); add(1, 'revised');
  const media = store.getEntity('media:t');
  assert.deepEqual(media?.kind === 'message' && media.message.parts?.map(p => p.id), ['p1', 'p2']);
  for (let i = 3; i <= 9; i++) add(i);
  assert.ok(store.getEntity('unsupported:content'));
});

test('versioned display checkpoint caps UTF8 bytes and never renders private system/reasoning text', async () => {
  const { store, consumer } = setup();
  await consumer.consume([start, { type: 'MESSAGES_SNAPSHOT', messages: [{ id: 's', role: 'system', content: 'PRIVATE_SYSTEM' }] },
    { type: 'REASONING_MESSAGE_CHUNK', messageId: 'reason', delta: 'PRIVATE_REASONING' },
    { type: 'RAW', event: { body: 'PRIVATE_RAW' } }, finish]);
  assert.equal(JSON.stringify(store.checkpoint()).includes('PRIVATE_'), false);
  const checkpoint = store.checkpoint();
  assert.throws(() => new AgUiViewStore(binding, { ...checkpoint, committedMessageIds: ['界'.repeat(750_000)] }), /budget/);
  assert.throws(() => new AgUiViewStore(binding, { ...checkpoint, endedMessageIds: Array.from({ length: 4097 }, (_, i) => String(i)) }), /budget/);
});

test('optional tool parent resolves the official-created owner after existing messages', async () => {
  const { store, consumer } = setup();
  await consumer.consume([start, { type: 'TEXT_MESSAGE_CHUNK', messageId: 'intro', role: 'assistant', delta: 'intro' },
    { type: 'TOOL_CALL_START', toolCallId: 'x', toolCallName: 'lookup' }, { type: 'TOOL_CALL_ARGS', toolCallId: 'x', delta: '{}' }, { type: 'TOOL_CALL_END', toolCallId: 'x' }, finish]);
  const row = store.getEntity('tool:x');
  assert.equal(row?.kind === 'activity' && row.segment.activities[0]?.detail?.type === 'tool' && row.segment.activities[0].detail.arguments, '{}');
});
test('official unbound tool results remain visible with unknown execution', () => {
  const store = new AgUiViewStore(binding);
  store.apply({ messages: [{ id: 'r', role: 'tool', toolCallId: 'unbound', content: 'Observed result' }], state: {} });
  const rows = store.getSnapshot().itemIds.map(id => store.getEntity(id));
  assert.match(JSON.stringify(rows), /Observed result/); assert.match(JSON.stringify(rows), /Unbound tool result/);
  assert.equal(store.getFacts().execution, 'unknown');
});
test('replacement rebuilds tool execution/result facts and follows official row order', () => {
  const store = new AgUiViewStore(binding);
  const proposal = { id: 'p', role: 'assistant' as const, toolCalls: [{ id: 'x', type: 'function' as const, function: { name: 'lookup', arguments: '{}' } }] };
  store.apply({ messages: [proposal, { id: 'e', role: 'activity', activityType: 'tool_execution', content: { tool_call_id: 'x', status: 'completed' } }, { id: 'r', role: 'tool', toolCallId: 'x', content: 'old result' }], state: {} });
  store.onEvent({ type: 'MESSAGES_SNAPSHOT', messages: [proposal] } as never); store.apply({ messages: [proposal], state: {} });
  const tool = store.getEntity('tool:x'); assert.equal(tool?.kind, 'activity');
  if (tool?.kind !== 'activity' || tool.segment.activities[0]?.detail?.type !== 'tool') throw new Error('missing tool');
  assert.equal(tool.segment.activities[0].detail.phase, 'preparing'); assert.equal(tool.segment.activities[0].detail.result, undefined);
  const a = { id: 'a', role: 'user' as const, content: 'a' }; const b = { id: 'b', role: 'user' as const, content: 'b' };
  store.onEvent({ type: 'MESSAGES_SNAPSHOT', messages: [a, b] } as never); store.apply({ messages: [a, b], state: {} });
  const rowA = store.getEntity('message:a');
  store.onEvent({ type: 'MESSAGES_SNAPSHOT', messages: [b, a] } as never); store.apply({ messages: [b, a], state: {} });
  assert.deepEqual(store.getSnapshot().itemIds, ['message:b', 'message:a']); assert.equal(store.getEntity('message:a'), rowA);
  assert.deepEqual(store.checkpoint().entities.map(entity => entity.id), ['message:b', 'message:a']);
});
test('delivery assessments preserve actual safe unmet requirements without inventing recovery actions', () => {
  const store = new AgUiViewStore(binding);
  store.onEvent({ type: 'CUSTOM', name: 'zebra.delivery_assessment.v1', value: { status: 'partial', task_type: 'research', goal: 'Verify sources', satisfied: ['Read public evidence'], unmet: ['Missing signed file'], required_outcomes: ['Signed file'], evidence_refs: ['evidence:1'], artifact_refs: [] } } as never);
  assert.equal(store.getFacts().deliveryAssessment?.goal, 'Verify sources');
  assert.deepEqual(store.getFacts().deliveryAssessment?.unmet, ['Missing signed file']);
  assert.deepEqual(store.getRunState().availableActions, []);
});

test('replacement rebuild handles results before proposals and preserves independent assessment facts', () => {
  const store = new AgUiViewStore(binding);
  store.onEvent({ type: 'CUSTOM', name: 'zebra.delivery_assessment.v1', value: { status: 'blocked', unmet: Array.from({ length: 70 }, () => 'Need evidence') } } as never);
  const messages = [{ id: 'result', role: 'tool' as const, toolCallId: 'x', content: 'observed result' }, { id: 'p', role: 'assistant' as const, toolCalls: [{ id: 'x', type: 'function' as const, function: { name: 'lookup', arguments: '{}' } }] }];
  store.onEvent({ type: 'MESSAGES_SNAPSHOT', messages } as never); store.apply({ messages, state: {} });
  const tool = store.getEntity('tool:x'); assert.equal(tool?.kind === 'activity' && tool.segment.activities[0]?.detail?.type === 'tool' && tool.segment.activities[0].detail.result, 'observed result');
  assert.equal(store.getEntity('result:result'), undefined); assert.equal(store.getFacts().delivery, 'blocked');
  assert.equal(store.getFacts().deliveryAssessment?.previewTruncated, true);
});

test('valid standard activity and child IDs cannot overwrite synthetic message/tool identities', async () => {
  const { store, consumer } = setup();
  await consumer.consume([start, { type: 'TEXT_MESSAGE_CHUNK', messageId: 'a', role: 'assistant', delta: 'Keep message' },
    { type: 'TOOL_CALL_START', toolCallId: 'x', toolCallName: 'lookup', parentMessageId: 'p' }, { type: 'TOOL_CALL_ARGS', toolCallId: 'x', delta: '{}' }, { type: 'TOOL_CALL_END', toolCallId: 'x' },
    { type: 'ACTIVITY_SNAPSHOT', messageId: 'message:a', activityType: 'tests', content: { status: 'completed' } },
    { type: 'ACTIVITY_SNAPSHOT', messageId: 'tool:x', activityType: 'tests', content: { status: 'completed' } },
    { type: 'SUBAGENT_STARTED', subagentRunId: 'tool:x', name: 'Child' }, { type: 'SUBAGENT_FINISHED', subagentRunId: 'tool:x' }, finish]);
  assert.equal(store.getEntity('message:a')?.kind, 'message');
  const tool = store.getEntity('tool:x'); assert.equal(tool?.kind === 'activity' && tool.segment.activities[0]?.detail?.type, 'tool');
  assert.ok(store.getEntity('activity:message:a')); assert.ok(store.getEntity('activity:tool:x')); assert.ok(store.getEntity('child:tool:x'));
});
test('replacement before argument END retains preparing rather than inventing a proposal', async () => {
  const { store, consumer } = setup();
  async function* source() {
    yield start; yield { type: 'TOOL_CALL_START', toolCallId: 'x', toolCallName: 'lookup', parentMessageId: 'p' };
    yield { type: 'TOOL_CALL_ARGS', toolCallId: 'x', delta: '{"x":' };
    yield { type: 'MESSAGES_SNAPSHOT', messages: [{ id: 'p', role: 'assistant', toolCalls: [{ id: 'x', type: 'function', function: { name: 'lookup', arguments: '{"x":' } }] }] };
  }
  await consumer.consume(source());
  const tool = store.getEntity('tool:x'); assert.equal(tool?.kind === 'activity' && tool.segment.activities[0]?.detail?.type === 'tool' && tool.segment.activities[0].detail.phase, 'preparing');
});

test('synthetic media cannot overwrite an ordinary message with the same public-looking ID', () => {
  const store = new AgUiViewStore(binding);
  store.onEvent({ type: 'CUSTOM', name: 'zebra.content_part', value: { tool_call_id: 'x', part: { id: 'part', type: 'file', state: 'ready', artifactId: 'artifact', mimeType: 'text/plain', name: 'Tool file' } } } as never);
  store.apply({ messages: [{ id: 'media:x', role: 'assistant', content: 'Independent public message' }], state: {} });
  const message = store.getEntity('message:media:x'); const media = store.getEntity('media:x');
  assert.equal(message?.kind === 'message' && message.message.content, 'Independent public message');
  assert.equal(message?.kind === 'message' && message.message.parts, undefined);
  assert.equal(media?.kind === 'message' && media.message.parts?.[0]?.id, 'part');
});

test('admitted user messages have no assistant draft presentation and cold snapshots preserve canonical order', () => {
  const store = new AgUiViewStore(binding);
  store.apply({ messages: [{ id: 'u', role: 'user', content: 'Admitted request' },
    { id: 'p', role: 'assistant', toolCalls: [{ id: 'c', type: 'function', function: { name: 'lookup', arguments: '{}' } }] },
    { id: 'a', role: 'assistant', content: 'Public answer' }], state: {} });
  const user = store.getEntity('message:u'); assert.equal(user?.kind === 'message' && user.message.presentation, undefined);
  assert.deepEqual(store.getSnapshot().itemIds, ['message:u', 'tool:c', 'message:a']);
});

test('first cold projection follows official user/proposal/answer order rather than tool-index construction order', () => {
  const store = new AgUiViewStore(binding);
  store.apply({ messages: [{ id: 'u', role: 'user', content: 'request' }, { id: 'p', role: 'assistant', toolCalls: [{ id: 'c', type: 'function', function: { name: 'lookup', arguments: '{}' } }] }, { id: 'a', role: 'assistant', content: 'answer' }], state: {} });
  assert.deepEqual(store.getSnapshot().itemIds, ['message:u', 'tool:c', 'message:a']);
});
