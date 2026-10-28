import assert from "node:assert/strict";
import test from "node:test";
import { StandardAgUiConsumer } from "../src/agui_reducer.ts";
const binding = { threadId: "thread", runId: "run" };
const start = { type: "RUN_STARTED", ...binding };
const end = { type: "RUN_FINISHED", ...binding, outcome: { type: "success" } };

test("cold 10k canonical events wait for application without overflow", async () => {
  let release!: () => void;
  let entered!: () => void;
  const gate = new Promise<void>(resolve => release = resolve);
  const ready = new Promise<void>(resolve => entered = resolve);
  let pulls = 0, observations = 0, returned = 0;
  const source = { async *[Symbol.asyncIterator]() {
    try {
      pulls++; yield start;
      for (let i = 0; i < 10000; i++) { pulls++; yield { type: "CUSTOM", name: "progress", value: i }; }
      pulls++; yield end;
    } finally { returned++; }
  } };
  const consumer = new StandardAgUiConsumer(binding, { onEvent: async () => {
    observations++;
    if (observations === 1) { entered(); await gate; }
  } });
  const result = consumer.consume(source);
  void result.catch(() => {});
  await ready;
  await new Promise(resolve => setTimeout(resolve, 20));
  try { assert.ok(pulls <= 2, `application was stalled but source pulled ${pulls} events`); }
  finally { release(); }
  assert.equal((await result).status, "finished");
  assert.equal(observations, 10002);
  assert.equal(returned, 1);
});

test("trusted initial messages and state support deltas without deleting retained history", async () => {
  const initialMessages = [{ id: "history", role: "assistant" as const, content: "retained" }];
  const initialState = { value: 1 };
  const consumer = new StandardAgUiConsumer(binding, { initialMessages, initialState });
  await consumer.consume([start, { type: "STATE_DELTA", delta: [{ op: "replace", path: "/value", value: 2 }] }, end]);
  assert.deepEqual(consumer.snapshot.messages, initialMessages);
  assert.deepEqual(consumer.snapshot.state, { value: 2 });
  assert.deepEqual(initialState, { value: 1 });
});

test("private pacing survives chunk expansion, unknown drops and hostile barrier names", async () => {
  const events: string[] = [];
  const consumer = new StandardAgUiConsumer(binding, { onEvent: event => { events.push(event.type); } });
  await consumer.consume([start, { type: "FUTURE", value: "drop" },
    { type: "TEXT_MESSAGE_CHUNK", messageId: "m", delta: "a" },
    { type: "TEXT_MESSAGE_CHUNK", messageId: "m", delta: "b" },
    { type: "CUSTOM", name: "application-barrier", value: "business" },
    { type: "RAW", event: "noop" }, end]);
  assert.equal(consumer.snapshot.messages[0]?.content, "ab");
  assert.equal(events.filter(type => type === "CUSTOM").length, 1);
  assert.equal(events.filter(type => type === "RAW").length, 1);
  assert.equal(events.at(-1), "RUN_FINISHED");
});

test("abort rejects blocked application and requests source cleanup exactly once", async () => {
  const controller = new AbortController();
  let returned = 0, entered!: () => void, release!: () => void;
  const ready = new Promise<void>(resolve => entered = resolve);
  const blocked = new Promise<void>(resolve => release = resolve);
  const consumer = new StandardAgUiConsumer(binding, {
    signal: controller.signal, onEvent: async () => { entered(); await blocked; },
  });
  const source = { [Symbol.asyncIterator]() { return {
    next: async () => ({ done: false, value: start }),
    return: async () => { returned++; return { done: true, value: undefined }; },
  }; } };
  const result = consumer.consume(source);
  await ready;
  controller.abort(new Error("host stopped"));
  await assert.rejects(result, /host stopped/);
  assert.equal(returned, 1);
  assert.equal(consumer.snapshot.status, "failed");
  release();
});

test("callback rejection survives throwing iterator cleanup and pulls no later event", async () => {
  const original = new Error("application refused");
  let pulls = 0;
  const consumer = new StandardAgUiConsumer(binding, { onEvent: () => { throw original; } });
  await assert.rejects(consumer.consume({ [Symbol.asyncIterator]() { return {
    next: async () => { pulls++; return { done: false, value: start }; },
    return: () => { throw new Error("cleanup refused"); },
  }; } }), error => error === original);
  assert.ok(pulls <= 2);
});

test("canonical source objects enforce UTF8 byte budget before application", async () => {
  const consumer = new StandardAgUiConsumer(binding);
  await assert.rejects(consumer.consume([start, { type: "CUSTOM", name: "huge", value: "你".repeat(800000) }]), /byte budget/);
  assert.equal(consumer.snapshot.status, "failed");
});

test("abort rejects blocked source IO while requesting its owned cleanup", async () => {
  const controller = new AbortController();
  let blocked!: () => void, release!: (value: IteratorResult<unknown>) => void;
  const ready = new Promise<void>(resolve => blocked = resolve);
  const pending = new Promise<IteratorResult<unknown>>(resolve => release = resolve);
  let pulls = 0, returned = 0;
  const consumer = new StandardAgUiConsumer(binding, { signal: controller.signal });
  const result = consumer.consume({ [Symbol.asyncIterator]() { return {
    next: async () => { if (++pulls === 1) return { done: false, value: start }; blocked(); return pending; },
    return: async () => { returned++; return { done: true, value: undefined }; },
  }; } });
  await ready;
  controller.abort(new Error("IO stopped"));
  await assert.rejects(result, /IO stopped/);
  assert.equal(returned, 1);
  release({ done: true, value: undefined });
});

test("slow post-application snapshot paces long canonical text and terminal", async () => {
  let snapshots = 0, pulls = 0;
  const consumer = new StandardAgUiConsumer(binding, { onSnapshot: async () => {
    snapshots++; await new Promise(resolve => setImmediate(resolve));
  } });
  async function* source() {
    pulls++; yield start;
    for (let index = 0; index < 1000; index++) {
      pulls++; yield { type: "TEXT_MESSAGE_CHUNK", messageId: "m", delta: "x" };
    }
    pulls++; yield end;
  }
  const result = await consumer.consume(source());
  assert.equal(result.messages[0]?.content, "x".repeat(1000));
  assert.equal(result.status, "finished");
  assert.equal(pulls, 1002);
  assert.ok(snapshots >= 1000);
});

test("abort also rejects a blocked final status notification", async () => {
  const controller = new AbortController();
  let entered!: () => void, release!: () => void;
  const ready = new Promise<void>(resolve => entered = resolve);
  const blocked = new Promise<void>(resolve => release = resolve);
  const consumer = new StandardAgUiConsumer(binding, { signal: controller.signal,
    onSnapshot: async snapshot => { if (snapshot.status === "finished") { entered(); await blocked; } },
  });
  const result = consumer.consume([start, end]);
  await ready;
  controller.abort(new Error("final stopped"));
  const timeout = setTimeout(release, 100);
  try { await assert.rejects(result, /final stopped/); }
  finally { clearTimeout(timeout); release(); }
  assert.equal(consumer.snapshot.status, "failed");
});
