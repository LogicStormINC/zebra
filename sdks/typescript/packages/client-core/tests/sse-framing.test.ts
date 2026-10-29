import assert from "node:assert/strict";
import test from "node:test";
import { readSseRecords, SseProtocolError } from "../src/sse_records.ts";

function body(parts: Uint8Array[], close = true) {
  let cancelled = false;
  return { stream: new ReadableStream<Uint8Array>({
    start(controller) { for (const part of parts) controller.enqueue(part); },
    pull(controller) { if (close) controller.close(); }, cancel() { cancelled = true; },
  }), cancelled: () => cancelled };
}
const bytes = (text: string) => new TextEncoder().encode(text);

test("SSE preserves multiline data, optional spaces and split CRLF/UTF8", async () => {
  const wire = bytes('id: signed\r\ndata: {"a":\r\ndata: "你"}\r\n\r\n');
  const source = body(Array.from(wire, byte => Uint8Array.of(byte)));
  const records = [];
  for await (const record of readSseRecords(source.stream, 1024)) records.push(record);
  assert.deepEqual(records, [{ data: '{"a":\n"你"}', id: "signed" }]);
});

test("SSE refuses malformed UTF8 and truncated data without losing cleanup", async () => {
  for (const parts of [[Uint8Array.of(0xff)], [bytes('data: {"a":1}')], [bytes('data: x\n')]]) {
    const source = body(parts);
    await assert.rejects(async () => { for await (const _ of readSseRecords(source.stream, 1024)) {} }, SseProtocolError);
    assert.equal(source.stream.locked, false);
  }
});

test("SSE bounds actual record bytes and cancels on early return", async () => {
  const source = body([bytes("data: 你你\n\n")], false);
  await assert.rejects(async () => { for await (const _ of readSseRecords(source.stream, 10)) {} }, SseProtocolError);
  assert.equal(source.cancelled(), true);
  const next = body([bytes("data: 1\n\ndata: 2\n\n")], false);
  for await (const _ of readSseRecords(next.stream, 1024)) break;
  assert.equal(next.cancelled(), true);
  assert.equal(next.stream.locked, false);
});

test("legacy transport fails poison records once, after awaited application ACK", async () => {
  const { consumeClientEffectStream } = await import("../src/sse_stream.ts");
  let calls = 0;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 100);
  try {
    await assert.rejects(consumeClientEffectStream({
      fetchImpl: async () => { calls++; return new Response(bytes('data: invalid\n\n')); },
      streamUrl: "/stream", headers: () => ({}), stopped: () => false,
      signal: controller.signal, onEffect: async () => {},
    }), SseProtocolError);
    assert.equal(calls, 1);
  } finally { clearTimeout(timeout); }
});

test("abort interrupts a blocked underlying SSE reader", async () => {
  const { consumeClientEffectStream } = await import("../src/sse_stream.ts");
  let cancelled = 0;
  const controller = new AbortController();
  const stream = new ReadableStream<Uint8Array>({ cancel() { cancelled++; } });
  const consuming = consumeClientEffectStream({
    fetchImpl: async () => new Response(stream), streamUrl: "/stream",
    headers: () => ({}), stopped: () => false, signal: controller.signal,
    onEffect: async () => {},
  });
  await new Promise(resolve => setTimeout(resolve, 5));
  controller.abort();
  await Promise.race([consuming, new Promise((_resolve, reject) => setTimeout(() => reject(new Error("blocked reader was not cancelled")), 100))]);
  assert.equal(cancelled, 1);
  assert.equal(stream.locked, false);
});

test("legacy malformed envelopes and canonical chunks are permanent protocol failures", async () => {
  const { consumeClientEffectStream } = await import("../src/sse_stream.ts");
  for (const payload of [null, { type: "CUSTOM", name: "zebra.canonical_chunk", value: null },
    { type: "CUSTOM", name: "zebra.canonical_chunk", value: { chunk_index: 0, content: "bad", last: true } }]) {
    let calls = 0;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 100);
    try {
      await assert.rejects(consumeClientEffectStream({
        fetchImpl: async () => { calls++; return new Response(bytes(`data: ${JSON.stringify(payload)}\n\n`)); },
        streamUrl: "/stream", headers: () => ({}), stopped: () => false,
        signal: controller.signal, onEffect: async () => {},
      }), SseProtocolError);
      assert.equal(calls, 1);
    } finally { clearTimeout(timeout); }
  }
});

test("cursor ACK waits for asynchronous application", async () => {
  const { consumeClientEffectStream } = await import("../src/sse_stream.ts");
  const controller = new AbortController();
  let entered!: () => void, release!: () => void;
  const ready = new Promise<void>(resolve => entered = resolve);
  const gate = new Promise<void>(resolve => release = resolve);
  const cursors: (string | null)[] = [];
  const consuming = consumeClientEffectStream({
    fetchImpl: async () => new Response(bytes('id: signed\ndata: {"type":"CUSTOM","name":"business","value":1}\n\n')),
    streamUrl: "/stream", headers: () => ({}), stopped: () => false,
    signal: controller.signal, onEffect: async () => {},
    onCursor: cursor => { cursors.push(cursor); controller.abort(); },
    onObservation: async () => { entered(); await gate; },
  });
  await ready;
  assert.deepEqual(cursors, []);
  release();
  await consuming;
  assert.deepEqual(cursors, ["signed"]);
});

test("small SSE records do not allocate their configured ceiling", async () => {
  const source = body([bytes("data: 1\n\n")]);
  const original = globalThis.Uint8Array;
  let allocated = 0;
  globalThis.Uint8Array = new Proxy(original, { construct(target, args) {
    if (typeof args[0] === "number") allocated = Math.max(allocated, args[0]);
    return Reflect.construct(target, args);
  } });
  try {
    const records = [];
    for await (const record of readSseRecords(source.stream, 2 ** 40)) records.push(record);
    assert.equal(records[0]?.data, "1");
    assert.ok(allocated < 1_048_576, `small record allocated ${allocated} bytes`);
  } finally { globalThis.Uint8Array = original; }
});

test("byte budget includes CRLF framing bytes", async () => {
  const source = body([bytes("data: x\r\n\r\n")]);
  await assert.rejects(async () => { for await (const _ of readSseRecords(source.stream, 10)) {} }, SseProtocolError);
});

test("abort discards incomplete SSE bytes without a poison failure", async () => {
  const { consumeClientEffectStream } = await import("../src/sse_stream.ts");
  const controller = new AbortController();
  const stream = new ReadableStream<Uint8Array>({ start(source) { source.enqueue(bytes("data: incomplete")); } });
  const consuming = consumeClientEffectStream({
    fetchImpl: async () => new Response(stream), streamUrl: "/stream",
    headers: () => ({}), stopped: () => false, signal: controller.signal, onEffect: async () => {},
  });
  await new Promise(resolve => setTimeout(resolve, 5));
  controller.abort();
  await consuming;
  assert.equal(stream.locked, false);
});

test("canonical assembly bounds cumulative UTF8 bytes before final decoding", async () => {
  const { consumeClientEffectStream } = await import("../src/sse_stream.ts");
  const controller = new AbortController();
  let calls = 0, observed = 0;
  const wire = Array.from({ length: 150 }, (_, index) => `id: ${index}\ndata: ${JSON.stringify({
    type: "CUSTOM", name: "zebra.canonical_chunk", value: { chunk_index: index, content: "你".repeat(5000), last: false },
  })}\n\n`).join("");
  await assert.rejects(consumeClientEffectStream({
    fetchImpl: async () => { calls++; return new Response(calls === 1 ? wire : "", { status: calls === 1 ? 200 : 401 }); },
    streamUrl: "/stream", headers: () => ({}), stopped: () => false,
    signal: controller.signal, streamVersion: 2, onEffect: async () => {},
    onObservation: async () => { observed++; },
  }), /assembly exceeds bounds/);
  assert.equal(calls, 1);
  assert.equal(observed, 0);
});

test("consumed STATE_DELTA structure fails before callbacks, direct or assembled", async () => {
  const { consumeClientEffectStream } = await import("../src/sse_stream.ts");
  for (const delta of [{}, [null]]) for (const assembled of [false, true]) {
    const event = { type: "STATE_DELTA", delta };
    const data = assembled ? { type: "CUSTOM", name: "zebra.canonical_chunk",
      value: { chunk_index: 0, content: JSON.stringify(event), last: true } } : event;
    let calls = 0, observed = 0, effects = 0;
    await assert.rejects(consumeClientEffectStream({
      fetchImpl: async () => { calls++; return new Response(calls === 1 ? `data: ${JSON.stringify(data)}\n\n` : "", { status: calls === 1 ? 200 : 401 }); },
      streamUrl: "/stream", headers: () => ({}), stopped: () => false,
      signal: new AbortController().signal,
      onObservation: async () => { observed++; }, onEffect: async () => { effects++; },
    }), SseProtocolError);
    assert.equal(calls, 1);
    assert.equal(observed, 0);
    assert.equal(effects, 0);
  }
});
