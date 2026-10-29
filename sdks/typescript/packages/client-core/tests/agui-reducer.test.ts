import assert from "node:assert/strict";
import test from "node:test";
import { StandardAgUiConsumer } from "../src/agui_reducer.ts";
const binding = { threadId: "thread", runId: "run" };
const start = { type: "RUN_STARTED", ...binding };
const end = { type: "RUN_FINISHED", ...binding };
const text = [
  { type: "TEXT_MESSAGE_START", messageId: "m", role: "assistant" },
  { type: "TEXT_MESSAGE_CONTENT", messageId: "m", delta: "answer" }, { type: "TEXT_MESSAGE_END", messageId: "m" },
];
const consumer = () => new StandardAgUiConsumer(binding);

test("official snapshots replace and RFC6902 patches apply atomically with prototype rejection", async () => {
  const c = consumer();
  await c.consume([start,
    { type: "STATE_SNAPSHOT", snapshot: { discarded: true } },
    { type: "STATE_SNAPSHOT", snapshot: { list: [1, 2], old: "x" } },
    { type: "STATE_DELTA", delta: [
      { op: "test", path: "/old", value: "x" }, { op: "add", path: "/list/-", value: 3 },
      { op: "copy", from: "/old", path: "/copy" }, { op: "move", from: "/old", path: "/moved" },
      { op: "replace", path: "/copy", value: "y" }, { op: "remove", path: "/moved" },
    ] },
    end]);
  assert.deepEqual(c.snapshot.state, { list: [1, 2, 3], copy: "y" });
  assert.equal(({} as { polluted?: boolean }).polluted, undefined);
  assert.equal(c.snapshot.status, "finished");
});

test("falsy snapshots and message snapshots replace previous values", async () => {
  for (const snapshot of [null, 0, false, ""]) {
    const c = consumer();
    await c.consume([start, ...text, { type: "MESSAGES_SNAPSHOT", messages: [{ id: "saved", role: "user", content: "saved" }] }, { type: "STATE_SNAPSHOT", snapshot }, end]);
    assert.equal(c.snapshot.state, snapshot);
    assert.deepEqual(c.snapshot.messages, [{ id: "saved", role: "user", content: "saved" }]);
  }
});

test("official child activity, reasoning and tool results apply without executing effects", async () => {
  const c = consumer();
  await c.consume([start,
    { type: "SUBAGENT_STARTED", subagentRunId: "child", name: "research" },
    { type: "STEP_STARTED", stepName: "tools", subagentRunId: "child" },
    { type: "ACTIVITY_SNAPSHOT", messageId: "a", activityType: "progress", content: { n: 1 }, subagentRunId: "child" },
    { type: "ACTIVITY_DELTA", messageId: "a", activityType: "progress", patch: [{ op: "replace", path: "/n", value: 2 }], subagentRunId: "child" },
    { type: "REASONING_START", messageId: "span", subagentRunId: "child" },
    { type: "REASONING_MESSAGE_CHUNK", messageId: "reason", delta: "public reasoning", subagentRunId: "child" },
    { type: "REASONING_END", messageId: "span", subagentRunId: "child" },
    { type: "REASONING_ENCRYPTED_VALUE", subtype: "message", entityId: "reason", encryptedValue: "opaque-secret", subagentRunId: "child" },
    { type: "TOOL_CALL_CHUNK", toolCallId: "tool", toolCallName: "lookup", delta: "{}", subagentRunId: "child" },
    { type: "TOOL_CALL_RESULT", toolCallId: "tool", messageId: "result", content: "found", role: "tool", subagentRunId: "child" },
    { type: "STEP_FINISHED", stepName: "tools", subagentRunId: "child" },
    { type: "SUBAGENT_FINISHED", subagentRunId: "child" }, end]);
  const messages = c.snapshot.messages;
  assert.deepEqual(messages.find(m => m.id === "a"), { id: "a", role: "activity", activityType: "progress", content: { n: 2 }, subagentRunId: "child" });
  const reason = messages.find(m => m.id === "reason");
  assert.equal(reason?.role, "reasoning");
  assert.equal(reason?.content, "public reasoning");
  assert.equal(reason && "encryptedValue" in reason ? reason.encryptedValue : undefined, "opaque-secret");
  assert.equal(messages.find(m => m.id === "result")?.content, "found");
});

test("binding and child attribution reject before callbacks and state contamination", async () => {
  const seen: string[] = [];
  const c = new StandardAgUiConsumer(binding, { onEvent: e => { seen.push(e.type); } });
  await assert.rejects(c.consume([start, ...text, { ...end, runId: "other" }]));
  assert.deepEqual(seen, ["RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END"]);
  assert.equal(c.snapshot.messages[0]?.content, "answer");
  const child = consumer();
  await assert.rejects(child.consume([start,
    { type: "SUBAGENT_STARTED", subagentRunId: "child", name: "x" },
    { type: "ACTIVITY_SNAPSHOT", messageId: "a", activityType: "x", content: {}, subagentRunId: "child" },
    { type: "ACTIVITY_DELTA", messageId: "a", activityType: "x", patch: [], subagentRunId: "wrong-child" },
  ]));
});

test("independent thread/run instances and async error/truncation preserve accepted results", async () => {
  const a = consumer();
  const b = new StandardAgUiConsumer({ threadId: "other", runId: "other" });
  async function* broken() { yield start; yield* text; throw new Error("offline"); }
  await Promise.all([assert.rejects(a.consume(broken()), /offline/), b.consume([
    { type: "RUN_STARTED", threadId: "other", runId: "other" }, { type: "RUN_FINISHED", threadId: "other", runId: "other" },
  ])]);
  assert.equal(a.snapshot.messages[0]?.content, "answer");
  assert.deepEqual(b.snapshot.messages, []);
  assert.equal(a.snapshot.status, "failed");
  const truncated = consumer();
  await truncated.consume([start, ...text]);
  assert.equal(truncated.snapshot.status, "incomplete");
  assert.equal(truncated.snapshot.messages[0]?.content, "answer");
  const errored = consumer();
  await errored.consume([start, ...text, { type: "RUN_ERROR", message: "producer error" }]);
  assert.equal(errored.snapshot.status, "error");
  assert.equal(errored.snapshot.messages[0]?.content, "answer");
  await assert.rejects(truncated.consume([start, end]), /once/);
});

async function interrupted(interrupts: { id: string; reason: string; expiresAt?: string }[] = [{ id: "a", reason: "approval" }, { id: "b", reason: "input" }]) {
  const c = consumer();
  await c.consume([start, { ...end, outcome: { type: "interrupt", interrupts } }]);
  return c;
}

test("resume preflight rejects missing/duplicate/old/expired answers and allows expired cancellation", async () => {
  const c = await interrupted();
  assert.throws(() => c.prepareResume({ ...binding, runId: "old" }, [{ interruptId: "a", status: "resolved" }]), /binding/);
  assert.throws(() => c.prepareResume(binding, [{ interruptId: "a", status: "resolved" }]), /missing/);
  assert.throws(() => c.prepareResume(binding, [{ interruptId: "a", status: "resolved" }, { interruptId: "a", status: "cancelled" }]), /duplicate/);
  assert.throws(() => c.prepareResume(binding, [{ interruptId: "old", status: "resolved" }]), /unknown|missing/);
  const entries = [{ interruptId: "a", status: "resolved" as const, payload: [true, 2] }, { interruptId: "b", status: "cancelled" as const }];
  assert.deepEqual(c.prepareResume(binding, entries), entries);
  assert.throws(() => c.prepareResume(binding, [...entries, { interruptId: "old", status: "cancelled" }]), /unknown/);
  const expired = await interrupted([{ id: "a", reason: "approval", expiresAt: "2000-01-01T00:00:00Z" }]);
  assert.throws(() => expired.prepareResume(binding, [{ interruptId: "a", status: "resolved", payload: true }]), /expired/);
  assert.deepEqual(expired.prepareResume(binding, [{ interruptId: "a", status: "cancelled" }]), [{ interruptId: "a", status: "cancelled" }]);
  assert.throws(() => consumer().prepareResume(binding, []), /interrupt/);
});

test("callback and snapshot copies cannot alias internal state", async () => {
  const c = new StandardAgUiConsumer(binding, { onEvent: event => { event.type = "CUSTOM" as typeof event.type; } });
  await c.consume([start, ...text, end]);
  c.snapshot.messages.length = 0;
  assert.equal(c.snapshot.messages.length, 1);
  assert.equal(start.type, "RUN_STARTED");
});

test("activity snapshot overwrite, child error and cancelled outcomes", async () => {
  const c = consumer();
  await c.consume([start,
    { type: "ACTIVITY_SNAPSHOT", messageId: "a", activityType: "progress", content: { old: true } },
    { type: "ACTIVITY_SNAPSHOT", messageId: "a", activityType: "progress", content: { n: 1 } },
    { type: "SUBAGENT_STARTED", subagentRunId: "child", name: "research" },
    { type: "SUBAGENT_ERROR", subagentRunId: "child", message: "failed" },
    { type: "RAW", event: { native: "opaque" } }, { type: "CUSTOM", name: "extension", value: 3 },
    { ...end, outcome: { type: "cancelled" } },
  ]);
  assert.deepEqual(c.snapshot.messages.find(m => m.id === "a")?.content, { n: 1 });
  assert.deepEqual(c.snapshot.terminal?.outcome, { type: "cancelled" });
  assert.deepEqual(c.snapshot.pendingInterrupts, []);
});

test("resume preflight is schema checked, expiry conservative and duplicate pending IDs rejected", async () => {
  const c = await interrupted([{ id: "__proto__", reason: "input" }]);
  assert.deepEqual(c.prepareResume(binding, [{ interruptId: "__proto__", status: "resolved", payload: false }]), [{ interruptId: "__proto__", status: "resolved", payload: false }]);
  assert.throws(() => c.prepareResume(binding, [{ interruptId: "__proto__", status: "resolved", payload: null }]), /non-null/);
  assert.throws(() => c.prepareResume(binding, [{ interruptId: "__proto__", status: "invalid" as "resolved" }]));
  const duplicate = await interrupted([{ id: "a", reason: "input" }, { id: "a", reason: "approval" }]);
  assert.throws(() => duplicate.prepareResume(binding, [{ interruptId: "a", status: "cancelled" }]), /duplicate/);
  const invalidExpiry = await interrupted([{ id: "a", reason: "input", expiresAt: "not-a-date" }]);
  assert.throws(() => invalidExpiry.prepareResume(binding, [{ interruptId: "a", status: "resolved" }]), /expiry/);
  assert.deepEqual(invalidExpiry.prepareResume(binding, [{ interruptId: "a", status: "cancelled" }]), [{ interruptId: "a", status: "cancelled" }]);
});

test("consumer performs no fetch, POST or automatic tool execution, including replay", async () => {
  const originalFetch = globalThis.fetch;
  let requests = 0;
  globalThis.fetch = async () => { requests++; throw new Error("unexpected network"); };
  try {
    for (let replay = 0; replay < 2; replay++) {
      const c = consumer();
      await c.consume([start, { type: "TOOL_CALL_CHUNK", toolCallId: "effect", toolCallName: "dangerous", delta: "{}" }, end]);
      assert.equal(c.snapshot.messages[0]?.role, "assistant");
      assert.equal(c.snapshot.messages[0]?.role === "assistant" ? c.snapshot.messages[0].toolCalls?.[0]?.function.name : undefined, "dangerous");
    }
    assert.equal(requests, 0);
  } finally { globalThis.fetch = originalFetch; }
});


test("invalid state/activity patches explicitly fail, preserving accepted base and skipping terminal", async () => {
  for (const activity of [false, true]) {
    for (const patch of [
      [{ op: "replace", path: "/n", value: 2 }, { op: "remove", path: "/missing" }],
      [{ op: "add", path: "/__proto__/polluted", value: true }],
      [{ op: "add", path: "/constructor/prototype/polluted", value: true }],
    ]) {
      const c = consumer();
      await assert.rejects(c.consume([start,
        activity ? { type: "ACTIVITY_SNAPSHOT", messageId: "a", activityType: "progress", content: { n: 1 } }
          : { type: "STATE_SNAPSHOT", snapshot: { n: 1 } },
        activity ? { type: "ACTIVITY_DELTA", messageId: "a", activityType: "progress", patch }
          : { type: "STATE_DELTA", delta: patch }, end]));
      assert.deepEqual(activity ? c.snapshot.messages[0]?.content : c.snapshot.state, { n: 1 });
      assert.equal(c.snapshot.status, "failed");
      assert.equal(c.snapshot.terminal, undefined);
      assert.equal(({} as { polluted?: boolean }).polluted, undefined);
    }
  }
  for (const event of [
    { type: "STATE_DELTA", delta: [{ op: "add", path: "/n", value: 1 }] },
    { type: "ACTIVITY_DELTA", messageId: "missing", activityType: "progress", patch: [] },
  ]) await assert.rejects(consumer().consume([start, event, end]), /base/);
});

test("resume arbitrary JSON stays data and unsupported non-JSON values fail", async () => {
  const c = await interrupted([{ id: "a", reason: "input" }]);
  for (const payload of [false, 0, "", [null, true], { nested: [1, "x"] }]) {
    assert.deepEqual(c.prepareResume(binding, [{ interruptId: "a", status: "resolved", payload }]), [{ interruptId: "a", status: "resolved", payload }]);
  }
  for (const payload of [NaN, Infinity, 1n, () => 1, { invalid: undefined }]) {
    assert.throws(() => c.prepareResume(binding, [{ interruptId: "a", status: "resolved", payload }]), /JSON/);
  }
});

test("application callback throw/reject fails in production mode and suppresses queued deliveries", async () => {
  const originalNodeEnv = process.env.NODE_ENV;
  process.env.NODE_ENV = "production";
  try {
    for (const asynchronous of [false, true]) {
      const seen: string[] = [];
      const c = new StandardAgUiConsumer(binding, { onEvent: event => {
        seen.push(event.type);
        if (event.type === "TEXT_MESSAGE_CONTENT") {
          if (asynchronous) return Promise.reject(new Error("application rejected"));
          throw new Error("application rejected");
        }
      } });
      await assert.rejects(c.consume([start, ...text, end]), /application rejected/);
      assert.deepEqual(seen, ["RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT"]);
      assert.equal(c.snapshot.status, "failed");
      assert.equal(c.snapshot.terminal, undefined);
      assert.notEqual(c.snapshot.messages[0]?.content, "answer");
    }
  } finally {
    if (originalNodeEnv === undefined) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = originalNodeEnv;
  }
});

test("post-apply snapshots expose live accepted text/state before terminal and callback failures reject", { timeout: 2000 }, async () => {
  const observed: { status: string; text: unknown; state: unknown }[] = [];
  let resolveState!: () => void;
  const stateApplied = new Promise<void>(resolve => { resolveState = resolve; });
  const c = new StandardAgUiConsumer(binding, { onSnapshot: snapshot => {
    observed.push({ status: snapshot.status, text: snapshot.messages[0]?.content, state: snapshot.state });
    if ((snapshot.state as { n?: number })?.n === 1) resolveState();
  } });
  async function* live() {
    yield start;
    yield* text;
    yield { type: "STATE_SNAPSHOT", snapshot: { n: 1 } };
    await stateApplied;
    assert.ok(observed.some(s => s.status === "consuming" && s.text === "answer"));
    assert.ok(observed.some(s => s.status === "consuming" && (s.state as { n?: number }).n === 1));
    yield end;
  }
  await c.consume(live());
  assert.equal(observed.at(-1)?.status, "finished");
  for (const asynchronous of [false, true]) {
    const failing = new StandardAgUiConsumer(binding, { onSnapshot: () => {
      if (asynchronous) return Promise.reject(new Error("snapshot rejected"));
      throw new Error("snapshot rejected");
    } });
    await assert.rejects(failing.consume([start, ...text, end]), /snapshot rejected/);
    assert.equal(failing.snapshot.status, "failed");
  }
});

function deferred<T = void>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

test("callback/patch failure ends a blocked live subscription and requests iterator cleanup", { timeout: 2000 }, async () => {
  for (const patchFailure of [false, true]) {
    let returned = 0;
    const blocked = deferred<IteratorResult<unknown>>();
    const frames = patchFailure ? [start, { type: "STATE_SNAPSHOT", snapshot: { n: 1 } },
      { type: "STATE_DELTA", delta: [{ op: "remove", path: "/missing" }] }] : [start, ...text.slice(0, 2)];
    const source: AsyncIterable<unknown> = { [Symbol.asyncIterator]() {
      let index = 0;
      return { next: async () => index < frames.length ? { done: false, value: frames[index++] } : blocked.promise,
        return: async () => { returned++; return { done: true, value: undefined }; } };
    } };
    const c = new StandardAgUiConsumer(binding, { onEvent: event => {
      if (!patchFailure && event.type === "TEXT_MESSAGE_CONTENT") throw new Error("live callback failed");
    } });
    try {
      await assert.rejects(c.consume(source), patchFailure ? /path/ : /live callback failed/);
      assert.equal(c.snapshot.status, "failed");
      assert.equal(c.snapshot.terminal, undefined);
      assert.equal(returned, 1, "unsubscribe must request iterator.return once even while next is pending");
      if (patchFailure) assert.deepEqual(c.snapshot.state, { n: 1 });
    } finally { blocked.resolve({ done: true, value: undefined }); }
  }
});

test("awaited snapshot backpressure prevents later text/state/terminal acceptance on resolve and reject", { timeout: 2000 }, async () => {
  for (const rejectSnapshot of [false, true]) {
    const entered = deferred();
    const release = deferred();
    const seen: string[] = [];
    let blockedOnce = false;
    const c = new StandardAgUiConsumer(binding, {
      onEvent: event => { seen.push(event.type); },
      onSnapshot: async snapshot => {
        if (!blockedOnce && (snapshot.state as { n?: number }).n === 1) {
          blockedOnce = true;
          entered.resolve();
          await release.promise;
        }
      },
    });
    const result = c.consume([start, { type: "STATE_SNAPSHOT", snapshot: { n: 1 } }, ...text,
      { type: "STATE_DELTA", delta: [{ op: "replace", path: "/n", value: 2 }] }, end]);
    const settled = result.then(value => ({ value }), error => ({ error }));
    await entered.promise;
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(seen, ["RUN_STARTED", "STATE_SNAPSHOT"]);
    assert.deepEqual(c.snapshot.messages, []);
    assert.deepEqual(c.snapshot.state, { n: 1 });
    assert.equal(c.snapshot.terminal, undefined);
    if (rejectSnapshot) {
      release.reject(new Error("delayed snapshot failed"));
      assert.match(String((await settled as { error: unknown }).error), /delayed snapshot failed/);
      assert.deepEqual(c.snapshot.messages, []);
      assert.deepEqual(c.snapshot.state, { n: 1 });
      assert.equal(c.snapshot.terminal, undefined);
      assert.equal(c.snapshot.status, "failed");
    } else {
      release.resolve();
      const final = await result;
      assert.equal(final.messages[0]?.content, "answer");
      assert.deepEqual(c.snapshot.state, { n: 2 });
      assert.equal(c.snapshot.status, "finished");
    }
  }
});

test("blocked snapshot pauses canonical source until the callback releases", { timeout: 2000 }, async () => {
  const entered = deferred();
  const release = deferred();
  let pulls = 0;
  async function* source() {
    pulls++; yield start;
    pulls++; yield { type: "STATE_SNAPSHOT", snapshot: { n: 1 } };
    pulls++; yield end;
  }
  const c = new StandardAgUiConsumer(binding, { onSnapshot: async () => { entered.resolve(); await release.promise; } });
  const result = c.consume(source());
  await entered.promise;
  await new Promise(resolve => setTimeout(resolve, 20));
  try { assert.ok(pulls <= 2); }
  finally { release.resolve(); }
  assert.equal((await result).status, "finished");
  assert.equal(pulls, 3);
});


test("canonical chunk expansion and mutation-free RAW/CUSTOM events release queue counts", async () => {
  const c = consumer();
  async function* paced() {
    yield start;
    yield { type: "STATE_SNAPSHOT", snapshot: {} };
    yield* Array.from({ length: 20 }, (_, index) => ({ type: "TEXT_MESSAGE_CHUNK", messageId: `chunk-${index}`, delta: "x" }));
    for (let index = 0; index < 160; index++) {
      yield index % 2 ? { type: "RAW", event: index } : { type: "CUSTOM", name: "notice", value: index };
      await new Promise(resolve => setImmediate(resolve));
    }
    yield end;
  }
  await c.consume(paced());
  assert.equal(c.snapshot.messages.length, 20);
  assert.equal(c.snapshot.status, "finished");
});
