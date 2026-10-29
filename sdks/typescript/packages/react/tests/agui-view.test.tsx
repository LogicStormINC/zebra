import assert from 'node:assert/strict';
import test from 'node:test';
import { act, createElement } from 'react';
import { JSDOM } from 'jsdom';
import { AgUiViewStore } from '../../client-core/src/agui_view_store.ts';
import { StandardAgUiConsumer } from '../../client-core/src/agui_reducer.ts';
import { AgentAgUiConversation } from '../src/components/agent-agui-conversation.tsx';
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
async function mount() {
  const dom = new JSDOM('<!doctype html><div id="root"></div>');
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, Node: dom.window.Node });
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });
  const { createRoot } = await import('react-dom/client');
  const container = dom.window.document.getElementById('root')!;
  return { dom, container, root: createRoot(container) };
}
test('scoped bridge displays official applied output through existing widgets, local choices require submit', async () => {
  const binding = { threadId: 'thread', runId: 'run' }; const store = new AgUiViewStore(binding);
  const consumer = new StandardAgUiConsumer(binding, { onEvent: e => store.onEvent(e), onSnapshot: s => store.apply(s) });
  const { dom, container, root } = await mount(); let submitted = 0;
  await act(async () => { root.render(createElement(AgentAgUiConversation, { store, onDraft: () => { submitted++; } }));
    await consumer.consume([{ type: 'RUN_STARTED', ...binding },
      { type: 'TEXT_MESSAGE_CHUNK', messageId: 'm', role: 'assistant', delta: 'Public answer' },
      { type: 'RUN_FINISHED', ...binding, outcome: { type: 'interrupt', interrupts: [{ id: 'a', reason: 'approval_required', message: 'Permit tool?' }] } }]); });
  assert.match(container.querySelector('.zebra-agent-message-list')?.textContent ?? '', /Public answer/);
  const buttons = [...container.querySelectorAll('button')];
  await act(async () => buttons.find(b => b.textContent === 'Approve')!.click()); assert.equal(submitted, 0);
  await act(async () => [...container.querySelectorAll('button')].find(b => b.textContent === 'Prepare complete response set')!.click());
  assert.equal(submitted, 1);
  await act(async () => root.unmount()); dom.window.close();
});

test('actual producer media uses existing Artifact renderer and unchanged message DOM survives scoped updates/restoration', async () => {
  const { producerRecording } = await import('../../client-core/tests/agui-view-fixture.ts');
  const binding = { threadId: 'task', runId: 'public-run' }; const store = new AgUiViewStore(binding);
  const consumer = new StandardAgUiConsumer(binding, { onEvent: e => store.onEvent(e), onSnapshot: s => store.apply(s) });
  await consumer.consume(producerRecording());
  const { dom, container, root } = await mount(); let resolutions = 0;
  const resolveArtifact = async (id: string) => { resolutions++; return { artifactId: id, mimeType: 'image/png', url: 'https://media.example.test/public.png' }; };
  const contentRenderer = { resolveArtifact };
  await act(async () => root.render(createElement(AgentAgUiConversation, { store, contentRenderer })));
  assert.match(container.textContent!, /Public answer from actual producer/);
  assert.match(container.textContent!, /Evidence file/);
  const image = container.querySelector('img'); assert.ok(image);
  const calls = resolutions;
  await act(async () => { store.setConnection('disconnected'); store.setConnection('observing'); });
  assert.equal(container.querySelector('img'), image); assert.equal(resolutions, calls);
  const cold = new AgUiViewStore(binding, store.checkpoint()); cold.apply(consumer.snapshot);
  await act(async () => root.render(createElement(AgentAgUiConversation, { store: cold, contentRenderer })));
  assert.match(container.textContent!, /Public answer from actual producer/);
  assert.match(container.textContent!, /Evidence file/);
  await act(async () => { await waitForAnnouncement(); });
  assert.deepEqual([...container.querySelectorAll('.zebra-agent-turn__announcement')].map(node => node.textContent).filter(Boolean), []);
  await act(async () => root.unmount()); dom.window.close();
});

test('same interrupt IDs across simultaneous panels have unique labels and unsupported input stays visible', async () => {
  const { AgentApproval, AgentClarification } = await import('../src/components/agent-interrupts.tsx');
  const { dom, container, root } = await mount();
  const approval = { approval_id: 'same', tool_name: 'safe tool', reason: 'Permission required' };
  const clarification = { clarification_id: 'same', question: 'Choose', choices: ['one'] };
  await act(async () => root.render(createElement('div', null,
    ...[1, 2].flatMap(index => [createElement(AgentApproval, { key: `a${index}`, approval, onDecision: () => {} }), createElement(AgentClarification, { key: `c${index}`, clarification, onRespond: () => {} })]))));
  const ids = [...container.querySelectorAll('[id]')].map(element => element.id); assert.equal(new Set(ids).size, ids.length);
  for (const section of container.querySelectorAll('[aria-labelledby]')) assert.ok(container.querySelector(`[id="${section.getAttribute('aria-labelledby')}"]`));
  const binding = { threadId: 'unsupported', runId: 'run' }; const store = new AgUiViewStore(binding);
  const consumer = new StandardAgUiConsumer(binding, { onEvent: e => store.onEvent(e), onSnapshot: s => store.apply(s) });
  await consumer.consume([{ type: 'RUN_STARTED', ...binding }, { type: 'RUN_FINISHED', ...binding, outcome: { type: 'interrupt', interrupts: [{ id: 'form', reason: 'clarification_required', responseSchema: { type: 'object', properties: { command: { type: 'string' } } }, message: 'Custom form' }] } }]);
  await act(async () => root.render(createElement(AgentAgUiConversation, { store })));
  assert.match(container.textContent!, /Custom form/); assert.match(container.textContent!, /requires a Host renderer/);
  assert.equal(container.querySelector('input'), null);
  await act(async () => root.unmount()); dom.window.close();
});

test('1/3/12 parallel React views keep unrelated rows and media renderer calls isolated', async () => {
  for (const count of [1, 3, 12]) {
    const stores = Array.from({ length: count }, (_, index) => {
      const store = new AgUiViewStore({ threadId: `t${index}`, runId: `r${index}` });
      store.apply({ messages: [{ id: 'same-message-id', role: 'assistant', content: `scope-${index}` }], state: {} }); return store;
    });
    const renders = new Map<string, number>();
    const contentRenderer = { renderText: (part: { text: string }) => { renders.set(part.text, (renders.get(part.text) ?? 0) + 1); return part.text; } };
    const { dom, container, root } = await mount();
    await act(async () => root.render(createElement('div', null, ...stores.map((store, index) => createElement(AgentAgUiConversation, { key: index, store, contentRenderer })))));
    const before = stores.slice(1).map((_, index) => renders.get(`scope-${index + 1}`));
    const consumer = new StandardAgUiConsumer(stores[0]!.binding, { onEvent: e => stores[0]!.onEvent(e), onSnapshot: s => stores[0]!.apply(s) });
    await act(async () => { await consumer.consume([{ type: 'RUN_STARTED', ...stores[0]!.binding },
      { type: 'MESSAGES_SNAPSHOT', messages: [{ id: 'same-message-id', role: 'assistant', content: 'changed-scope-0' }] }, { type: 'RUN_FINISHED', ...stores[0]!.binding }]); });
    assert.match(container.textContent!, /changed-scope-0/);
    assert.deepEqual(stores.slice(1).map((_, index) => renders.get(`scope-${index + 1}`)), before);
    await act(async () => root.unmount()); dom.window.close();
  }
});

test('partial delivery displays actual unmet requirements as escaped text', async () => {
  const store = new AgUiViewStore({ threadId: 't', runId: 'r' });
  store.onEvent({ type: 'CUSTOM', name: 'zebra.delivery_assessment.v1', value: { status: 'blocked', goal: 'Verify evidence', unmet: ['<script>missing file</script>'], satisfied: [], evidence_refs: [], artifact_refs: [] } } as never);
  const { dom, container, root } = await mount();
  await act(async () => root.render(createElement(AgentAgUiConversation, { store })));
  assert.match(container.textContent!, /Verify evidence/); assert.match(container.textContent!, /<script>missing file<\/script>/);
  assert.equal(container.querySelector('script'), null);
  await act(async () => root.unmount()); dom.window.close();
});

test('bridge keeps an ordinary message and synthetic media with colliding source-looking IDs visible', async () => {
  const store = new AgUiViewStore({ threadId: 't', runId: 'r' });
  store.onEvent({ type: 'CUSTOM', name: 'zebra.content_part', value: { tool_call_id: 'x', part: { id: 'file', type: 'file', state: 'ready', artifactId: 'artifact', mimeType: 'text/plain', name: 'Tool file' } } } as never);
  store.apply({ messages: [{ id: 'media:x', role: 'assistant', content: 'Independent public message' }], state: {} });
  const { dom, container, root } = await mount();
  await act(async () => root.render(createElement(AgentAgUiConversation, { store })));
  assert.match(container.textContent!, /Independent public message/); assert.match(container.textContent!, /Tool file/);
  await act(async () => root.unmount()); dom.window.close();
});

test('paused source execution never acquires the legacy synthetic terminal blocked status', async () => {
  const store = new AgUiViewStore({ threadId: 't', runId: 'r' });
  store.apply({ messages: [], state: { execution: { status: 'paused' } } });
  const { dom, container, root } = await mount();
  await act(async () => root.render(createElement(AgentAgUiConversation, { store })));
  assert.match(container.textContent!, /Paused/);
  assert.equal(container.querySelector('.zebra-agent-run-status--blocked'), null);
  assert.equal(container.textContent!.includes('Waiting for your input'), false);
  await act(async () => root.unmount()); dom.window.close();
});

function gate() { let resolve!: () => void; return { promise: new Promise<void>(done => { resolve = done; }), resolve: () => resolve() }; }
const waitForAnnouncement = () => new Promise(resolve => setTimeout(resolve, 350));

test('actual HttpAgent onApplied announces completed text exactly once across later execution completion', async () => {
  const { createServer } = await import('node:http');
  const { createAgUiHttpClient } = await import('../../client-core/src/agui_http.ts');
  const binding = { threadId: 'http-aria', runId: 'agui:' + 'b'.repeat(64) }; const store = new AgUiViewStore(binding);
  const endApplied = gate(), finish = gate(); let lastType = '';
  const server = createServer(async (_request, response) => {
    response.writeHead(200, { 'Content-Type': 'text/event-stream' });
    const write = (event: unknown) => response.write(`data: ${JSON.stringify(event)}\n\n`);
    write({ type: 'RUN_STARTED', ...binding }); write({ type: 'STATE_SNAPSHOT', snapshot: { execution: { status: 'running' } } });
    write({ type: 'TEXT_MESSAGE_START', messageId: 'answer', role: 'assistant' }); write({ type: 'TEXT_MESSAGE_CONTENT', messageId: 'answer', delta: 'Live answer' }); write({ type: 'TEXT_MESSAGE_END', messageId: 'answer' });
    await finish.promise;
    write({ type: 'STATE_DELTA', delta: [{ op: 'replace', path: '/execution/status', value: 'completed' }] }); write({ type: 'RUN_FINISHED', ...binding }); response.end();
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address(); assert.ok(address && typeof address === 'object');
  const origin = `http://127.0.0.1:${address.port}`;
  const client = createAgUiHttpClient({ url: '/observe', fetch: (url, init) => fetch(origin + url, init),
    admit: async (operation, input) => ({ operation, input: { ...input, runId: binding.runId } }), receipt: async () => { throw new Error('No reconciliation'); },
    onEvent: event => { lastType = event.type; store.onEvent(event); }, onApplied: agent => { store.apply(agent); if (lastType === 'TEXT_MESSAGE_END') endApplied.resolve(); } });
  const { dom, container, root } = await mount(); let observing: Promise<unknown> | undefined;
  try {
    await client.admit({ protocolVersion: '1.0', threadId: binding.threadId, runId: 'intent', messages: [], state: {}, tools: [], context: [], forwardedProps: {} });
    await act(async () => root.render(createElement(AgentAgUiConversation, { store })));
    await act(async () => { observing = client.observe(); await endApplied.promise; });
    await act(async () => { await waitForAnnouncement(); });
    assert.deepEqual([...container.querySelectorAll('.zebra-agent-turn__announcement')].map(node => node.textContent).filter(Boolean), ['Live answer']);
    await act(async () => { finish.resolve(); await observing; });
    await act(async () => { await waitForAnnouncement(); });
    assert.deepEqual([...container.querySelectorAll('.zebra-agent-turn__announcement')].map(node => node.textContent).filter(Boolean), ['Live answer']);
    assert.equal(container.querySelectorAll('.zebra-agent-turn__announcement').length, 1);
  } finally {
    await act(async () => { finish.resolve(); await observing?.catch(() => {}); root.unmount(); }); dom.window.close();
    server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve()));
  }
});

test('open recorded stream completes text at END and announces meaningful media labels through one pipeline', async () => {
  const binding = { threadId: 'recorded-aria', runId: 'run' }; const store = new AgUiViewStore(binding);
  const afterEnd = gate(), continueMedia = gate(), afterMedia = gate(), finish = gate();
  async function* source() {
    yield { type: 'RUN_STARTED', ...binding };
    yield { type: 'TEXT_MESSAGE_START', messageId: 'answer', role: 'assistant' };
    yield { type: 'TEXT_MESSAGE_CONTENT', messageId: 'answer', delta: 'Recorded answer' };
    yield { type: 'TEXT_MESSAGE_END', messageId: 'answer' };
    afterEnd.resolve(); await continueMedia.promise;
    yield { type: 'CUSTOM', name: 'zebra.content_part', value: { tool_call_id: 'file', part: { id: 'file', type: 'file', state: 'ready', artifactId: 'file', mimeType: 'text/plain', name: 'Evidence notes.txt' } } };
    afterMedia.resolve(); await finish.promise;
    yield { type: 'RUN_FINISHED', ...binding };
  }
  const consumer = new StandardAgUiConsumer(binding, { onEvent: event => store.onEvent(event), onSnapshot: snapshot => store.apply(snapshot) });
  const { dom, container, root } = await mount(); let consuming: Promise<unknown> | undefined;
  try {
    await act(async () => root.render(createElement(AgentAgUiConversation, { store })));
    await act(async () => { consuming = consumer.consume(source()); await afterEnd.promise; });
    const message = store.getEntity('message:answer'); assert.equal(message?.kind === 'message' && message.message.status, 'complete');
    assert.equal(container.querySelector('.zebra-agent-message__status--streaming'), null);
    await act(async () => { await waitForAnnouncement(); });
    assert.deepEqual([...container.querySelectorAll('.zebra-agent-turn__announcement')].map(node => node.textContent).filter(Boolean), ['Recorded answer']);
    await act(async () => { continueMedia.resolve(); await afterMedia.promise; });
    await act(async () => { await waitForAnnouncement(); });
    const announcements = [...container.querySelectorAll('.zebra-agent-turn__announcement')].map(node => node.textContent).filter(Boolean);
    assert.equal(announcements.length, 1); assert.match(announcements[0]!, /Evidence notes\.txt/);
  } finally { await act(async () => { continueMedia.resolve(); finish.resolve(); await consuming?.catch(() => {}); root.unmount(); }); dom.window.close(); }
});
