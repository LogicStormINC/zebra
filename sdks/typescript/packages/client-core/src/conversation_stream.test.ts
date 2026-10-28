import assert from "node:assert/strict";
import test from "node:test";
import { ConversationStreamReducer } from "./conversation_stream.ts";

const custom = (name: string, value: unknown) => ({ type: "CUSTOM", name, value });

test("drafts replace by stable id and only answer commits clear the draft label", () => {
  const reducer = new ConversationStreamReducer();
  const draft = { message_id: "message:call", generation_id: "gen", offset: 0, content_delta: "wrong" };
  reducer.observe(custom("zebra.stream.draft", draft));
  reducer.observe(custom("zebra.stream.draft", draft));
  assert.equal(reducer.snapshot()[0]?.content, "wrong");
  reducer.observe(custom("zebra.message_replace", { message_id: "message:call", chunk_index: 0, content: "correct", last: true }));
  reducer.observe(custom("zebra.stream.draft", { ...draft, offset: 1, content_delta: "late" }));
  assert.equal(reducer.snapshot()[0]?.content, "correct");
  assert.equal(reducer.snapshot()[0]?.presentation, "provisional");
  reducer.observe(custom("zebra.answer_committed", { model_call_id: "call", assistant_message: "final" }));
  assert.equal(reducer.snapshot().length, 1);
  assert.equal(reducer.snapshot()[0]?.content, "final");
  assert.equal(reducer.snapshot()[0]?.presentation, "committed");
});

test("generation gaps fail closed and reset preserves canonical content", () => {
  const reducer = new ConversationStreamReducer();
  assert.throws(() => reducer.observe(custom("zebra.stream.draft", { message_id: "x", generation_id: "g", offset: 1, content_delta: "suffix" })));
  reducer.observe(custom("zebra.message_replace", { message_id: "x", chunk_index: 0, content: "kept", last: true }));
  reducer.observe(custom("zebra.stream.reset", {}));
  assert.equal(reducer.snapshot()[0]?.content, "kept");
  reducer.observe(custom("zebra.stream.recovery_start", {}));
  assert.equal(reducer.snapshot().length, 0);
});

import { consumeClientEffectStream } from "./sse_stream.ts";
import { ClientRuntimeStateStore, isStreamCursor } from "./runtime_state.ts";

const record = (id: string, event: unknown) => `id: ${id}\ndata: ${JSON.stringify(event)}\n\n`;
const bytes = (content: string) => new TextEncoder().encode(content);

test("cold v2 recovery never dispatches historical effect adds", async () => {
  const abort = new AbortController();
  const effects: string[] = [];
  let recovered = 0;
  const payload = [
    record("start", custom("zebra.stream.recovery_start", {})),
    record("old-add", { type: "STATE_DELTA", delta: [{ op: "add", value: { effect_id: "old", status: "pending", execution_location: "client" } }] }),
    record("old-remove", { type: "STATE_DELTA", delta: [{ op: "remove", path: "/effects/old" }] }),
    record("caught-up", custom("zebra.stream.recovery_complete", {})),
    record("live-add", { type: "STATE_DELTA", delta: [{ op: "add", value: { effect_id: "live", status: "pending", execution_location: "client" } }] }),
  ].join("");
  await consumeClientEffectStream({
    fetchImpl: async () => new Response(payload), streamUrl: "https://fixture.test/stream", headers: () => ({}),
    stopped: () => false, signal: abort.signal, streamVersion: 2,
    onCursorRecovered: async () => { recovered++; },
    onEffect: async (effect) => { effects.push(effect.effect_id); abort.abort(); },
  });
  assert.equal(recovered, 1);
  assert.deepEqual(effects, ["live"]);
});

test("same-instance reconnect resumes acknowledged partial chunk after read error", async () => {
  const abort = new AbortController();
  const target = JSON.stringify({ type: "TOOL_CALL_ARGS", toolCallId: "tool", delta: "argument" });
  const split = Math.floor(target.length / 2);
  let requests = 0;
  let observed = 0;
  const cursors: string[] = [];
  await consumeClientEffectStream({
    fetchImpl: async (_url, init) => {
      requests++;
      if (requests === 1) {
        return new Response(new ReadableStream({ start(controller) {
          controller.enqueue(bytes(record("caught", custom("zebra.stream.recovery_complete", {})) + record("partial", custom("zebra.canonical_chunk", { chunk_index: 0, content: target.slice(0, split), last: false }))));
          setTimeout(() => controller.error(new Error("owned read fault")), 20);
        } }));
      }
      assert.equal((init?.headers as Record<string, string>)["Last-Event-ID"], "partial");
      return new Response(record("complete", custom("zebra.canonical_chunk", { chunk_index: 1, content: target.slice(split), last: true })));
    },
    streamUrl: "https://fixture.test/stream", headers: () => ({}), stopped: () => false,
    signal: abort.signal, streamVersion: 2,
    onCursor: (cursor) => { if (cursor) cursors.push(cursor); },
    onObservation: async (event) => { if (event.type === "TOOL_CALL_ARGS") { observed++; abort.abort(); } },
    onEffect: async () => assert.fail("unexpected effect"),
  });
  assert.equal(requests, 2);
  assert.equal(observed, 1);
  assert.deepEqual(cursors, ["caught", "partial", "complete"]);
});

test("failed awaited observation does not accept its cursor and cancels reader", async () => {
  const abort = new AbortController();
  let requests = 0;
  let cancelled = 0;
  let handled = 0;
  const cursors: string[] = [];
  const wire = record("accepted", custom("zebra.stream.reset", {}));
  await consumeClientEffectStream({
    fetchImpl: async (_url, init) => {
      requests++;
      assert.equal((init?.headers as Record<string, string>)["Last-Event-ID"], undefined);
      return new Response(new ReadableStream({
        start: (controller) => controller.enqueue(bytes(wire)),
        cancel: () => { cancelled++; },
      }));
    },
    streamUrl: "https://fixture.test/stream", headers: () => ({}), stopped: () => false, signal: abort.signal,
    onCursor: (cursor) => { if (cursor) cursors.push(cursor); },
    onObservation: async () => { handled++; if (handled === 1) throw new Error("owned observer fault"); abort.abort(); },
    onEffect: async () => assert.fail("unexpected effect"),
  });
  assert.equal(requests, 2);
  assert.ok(cancelled >= 1);
  assert.deepEqual(cursors, ["accepted"]);
});

test("bounded signed cursors survive session state restoration", () => {
  let raw: string | null = null;
  const storage = { getItem: () => raw, setItem: (_key: string, value: string) => { raw = value; } } as unknown as Storage;
  const store = new ClientRuntimeStateStore(storage, "session");
  const state = store.load();
  state.lastEventId = "v2." + "a".repeat(3000);
  store.save(state);
  assert.equal(store.load().lastEventId, state.lastEventId);
  assert.equal(isStreamCursor("x".repeat(4097)), false);
});

test("one network chunk containing many valid records does not exceed per-record limit", async () => {
  const abort = new AbortController();
  let observed = 0;
  const count = 2400;
  const body = Array.from({ length: count }, (_item, index) => record(`record-${index}`, custom("zebra.stream.reset", { padding: "a".repeat(2048) }))).join("");
  assert.ok(body.length > 4_194_304);
  await consumeClientEffectStream({
    fetchImpl: async () => new Response(body), streamUrl: "https://fixture.test/stream", headers: () => ({}), stopped: () => false, signal: abort.signal,
    onObservation: async () => { observed++; if (observed === count) abort.abort(); },
    onEffect: async () => assert.fail("unexpected effect"),
  });
  assert.equal(observed, count);
});

test("oversized unfinished record cancels response without accepting a cursor", async () => {
  const abort = new AbortController();
  let requests = 0;
  let cancelled = 0;
  const cursors: string[] = [];
  await consumeClientEffectStream({
    fetchImpl: async () => {
      requests++;
      if (requests > 1) return new Response("", { status: 401 });
      return new Response(new ReadableStream({ start: controller => controller.enqueue(bytes("data: " + "a".repeat(8_388_609))), cancel: () => { cancelled++; } }));
    },
    streamUrl: "https://fixture.test/stream", headers: () => ({}), stopped: () => false, signal: abort.signal,
    onCursor: cursor => { if (cursor) cursors.push(cursor); }, onTerminalRejection: () => abort.abort(),
    onObservation: async () => assert.fail("unfinished record reached observer"),
    onEffect: async () => assert.fail("unexpected effect"),
  });
  assert.equal(requests, 2);
  assert.equal(cancelled, 1);
  assert.deepEqual(cursors, []);
});

test("a committed message cannot regress to a later draft or candidate replacement", () => {
  const reducer = new ConversationStreamReducer();
  reducer.observe(custom("zebra.answer_committed", { model_call_id: "call", assistant_message: "final" }));
  reducer.observe(custom("zebra.message_replace", { message_id: "message:call", chunk_index: 0, content: "late candidate", last: true }));
  reducer.observe(custom("zebra.stream.draft", { message_id: "message:call", generation_id: "gen", offset: 0, content_delta: "late draft" }));
  assert.equal(reducer.snapshot()[0]?.content, "final");
  assert.equal(reducer.snapshot()[0]?.presentation, "committed");
});


test("expired grant clears preview before rejection and preserves committed messages", async () => {
  const reducer = new ConversationStreamReducer();
  reducer.observe(custom("zebra.answer_committed", { model_call_id: "old", assistant_message: "kept" }));
  reducer.observe(custom("zebra.stream.draft", { message_id: "temporary", generation_id: "gen", offset: 0, content_delta: "preview" }));
  let rejected = false;
  await consumeClientEffectStream({
    fetchImpl: async () => new Response("", { status: 403 }), streamUrl: "https://fixture.test/stream",
    headers: () => ({}), stopped: () => false, signal: new AbortController().signal, streamVersion: 2,
    onObservation: async event => { reducer.observe(event); },
    onTerminalRejection: () => { assert.equal(reducer.snapshot().length, 1); rejected = true; },
    onEffect: async () => assert.fail("expired grant dispatched effect"),
  });
  assert.equal(rejected, true);
  assert.equal(reducer.snapshot()[0]?.content, "kept");
});


test("cold refresh retains two historical commits without model call ids", () => {
  const reducer = new ConversationStreamReducer();
  for (let repeat = 0; repeat < 2; repeat++) {
    reducer.observe(custom("zebra.stream.recovery_start", {}));
    for (const id of ["first", "second"]) {
      reducer.observe(custom("zebra.answer_committed", { message_id: `message:event:${id}`, model_call_id: null, assistant_message: id }));
    }
    assert.deepEqual(reducer.snapshot().map(message => message.id), ["message:event:first", "message:event:second"]);
  }
});

for (const kind of ["canonical", "draft-final", "replacement-middle", "replacement-final"] as const) {
  test(`actual consumer and stateful Host retry unacknowledged ${kind} once`, async () => {
    const reducer = new ConversationStreamReducer();
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), 4000);
    const id = "message:retry";
    let events: ReturnType<typeof custom>[];
    let failedIndex: number;
    if (kind === "canonical") {
      const assembled = JSON.stringify(custom("zebra.message_replace", { message_id: id, chunk_index: 0, content: "hello world", last: true }));
      const split = Math.floor(assembled.length / 2);
      events = [custom("zebra.canonical_chunk", { chunk_index: 0, content: assembled.slice(0, split), last: false }), custom("zebra.canonical_chunk", { chunk_index: 1, content: assembled.slice(split), last: true })];
      failedIndex = 1;
    } else if (kind === "draft-final") {
      events = ["hello ", "world"].map((content, index) => custom("zebra.stream.draft", { message_id: id, generation_id: "gen", offset: 0, chunk_index: index, content_delta: content, last: index === 1 }));
      failedIndex = 1;
    } else {
      events = ["hello", " ", "world"].map((content, index) => custom("zebra.message_replace", { message_id: id, chunk_index: index, content, last: index === 2 }));
      failedIndex = kind === "replacement-middle" ? 1 : 2;
    }
    let requests = 0;
    let failed = false;
    let observations = 0;
    const cursors: string[] = [];
    try {
      await consumeClientEffectStream({
        fetchImpl: async (_url, init) => {
          requests++;
          assert.ok(requests <= 2, "unacknowledged chunk retry did not converge");
          if (requests === 2) assert.equal((init?.headers as Record<string, string>)["Last-Event-ID"], `chunk-${failedIndex - 1}`);
          const start = requests === 1 || kind === "draft-final" ? 0 : failedIndex;
          const prefix = requests === 1 ? record("caught", custom("zebra.stream.recovery_complete", {})) : `data: ${JSON.stringify(custom("zebra.stream.reset", {}))}\n\n`;
          return new Response(prefix + events.slice(start).map((event, offset) => record(`chunk-${offset + start}`, event)).join(""));
        },
        streamUrl: "https://fixture.test/stream", headers: () => ({}), stopped: () => false, signal: abort.signal, streamVersion: 2,
        onObservation: async event => {
          reducer.observe(event);
          observations++;
          const value = event.value as { chunk_index?: number } | undefined;
          if (!failed && (kind === "canonical" ? event.name === "zebra.message_replace" : value?.chunk_index === failedIndex)) {
            failed = true;
            throw new Error("one-shot awaited Host rendering failure");
          }
        },
        onCursor: cursor => { if (cursor) cursors.push(cursor); if (cursor === `chunk-${events.length - 1}`) abort.abort(); },
        onEffect: async () => assert.fail("unexpected effect"),
      });
    } finally { clearTimeout(timer); }
    assert.equal(requests, 2);
    assert.equal(failed, true);
    assert.ok(observations >= 3);
    assert.equal(cursors.at(-1), `chunk-${events.length - 1}`);
    assert.equal(reducer.snapshot()[0]?.content, "hello world");
  });
}

test("unacknowledged reducer chunks accept exact replay and reject conflicting payload", () => {
  for (const name of ["zebra.stream.draft", "zebra.message_replace"]) {
    const reducer = new ConversationStreamReducer();
    const value = name.endsWith("draft")
      ? { message_id: "message:conflict", generation_id: "gen", offset: 0, chunk_index: 0, content_delta: "content", last: true }
      : { message_id: "message:conflict", chunk_index: 0, content: "content", last: true };
    const event = custom(name, value);
    reducer.observe(event);
    reducer.observe(event);
    assert.equal(reducer.snapshot()[0]?.content, "content");
    assert.throws(() => reducer.observe(custom(name, { ...value, last: false })), /Conflicting/);
    assert.throws(() => reducer.observe(custom(name, { ...value, content: "changed", content_delta: "changed" })), /Conflicting/);
  }
});

test("valid bounded canonical DEL source survives legacy ASCII expansion", async () => {
  const abort = new AbortController();
  const content = "\u007f".repeat(800000);
  const event = { event_type: "model_response_received", payload: { assistant_message: content } };
  const normalized = JSON.stringify(event);
  assert.ok(bytes(normalized).length < 1_048_576);
  const wire = `id: valid-durable\ndata: ${normalized.replaceAll("\u007f", "\\u007f")}\n\n`;
  assert.ok(bytes(wire).length > 4_194_304);
  let observed = 0;
  await consumeClientEffectStream({
    fetchImpl: async () => new Response(wire), streamUrl: "https://fixture.test/stream", headers: () => ({}), stopped: () => false, signal: abort.signal,
    onObservation: async value => { observed++; assert.deepEqual(value, event); },
    onCursor: cursor => { assert.equal(cursor, "valid-durable"); abort.abort(); },
    onEffect: async () => assert.fail("unexpected effect"),
  });
  assert.equal(observed, 1);
});

for (const callback of ["effect", "bootstrap"] as const) {
  test(`canonical assembly survives failed awaited ${callback} ACK`, async () => {
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), 4000);
    const target = callback === "bootstrap" ? custom("zebra.stream.recovery_complete", {})
      : { type: "STATE_DELTA", delta: [{ op: "add", value: { effect_id: "retry", status: "pending", execution_location: "client" } }] };
    const serialized = JSON.stringify(target);
    const split = Math.floor(serialized.length / 2);
    const first = record("prefix", custom("zebra.canonical_chunk", { chunk_index: 0, content: serialized.slice(0, split), last: false }));
    const final = record("final", custom("zebra.canonical_chunk", { chunk_index: 1, content: serialized.slice(split), last: true }));
    let requests = 0;
    let acknowledgements = 0;
    const ack = async () => { acknowledgements++; if (acknowledgements === 1) throw new Error("one-shot downstream failure"); };
    try {
      await consumeClientEffectStream({
        fetchImpl: async (_url, init) => {
          requests++;
          assert.ok(requests <= 2);
          if (requests === 2) assert.equal((init?.headers as Record<string, string>)["Last-Event-ID"], "prefix");
          return new Response((requests === 1 ? first : "") + final);
        },
        streamUrl: "https://fixture.test/stream", headers: () => ({}), stopped: () => false, signal: abort.signal,
        onObservation: async () => {}, onEffect: callback === "effect" ? ack : async () => assert.fail("unexpected effect"),
        ...(callback === "bootstrap" ? { onCursorRecovered: ack } : {}),
        onCursor: cursor => { if (cursor === "final") abort.abort(); },
      });
    } finally { clearTimeout(timer); }
    assert.equal(requests, 2);
    assert.equal(acknowledgements, 2);
  });
}

test("canonical unacknowledged final chunk rejects changed retry payload", async () => {
  const abort = new AbortController();
  let requests = 0;
  let observed = 0;
  const target = JSON.stringify({ type: "TOOL_CALL_ARGS", delta: "kept" });
  const split = Math.floor(target.length / 2);
  const cursors: string[] = [];
  await consumeClientEffectStream({
    fetchImpl: async () => {
      requests++;
      if (requests === 3) return new Response("", { status: 403 });
      return new Response((requests === 1 ? record("prefix", custom("zebra.canonical_chunk", { chunk_index: 0, content: target.slice(0, split), last: false })) : "") + record("final", custom("zebra.canonical_chunk", { chunk_index: 1, content: target.slice(split) + (requests === 2 ? " " : ""), last: true })));
    },
    streamUrl: "https://fixture.test/stream", headers: () => ({}), stopped: () => false, signal: abort.signal,
    onObservation: async event => { if (event.type === "TOOL_CALL_ARGS") { observed++; throw new Error("owned initial failure"); } },
    onCursor: cursor => { if (cursor) cursors.push(cursor); }, onTerminalRejection: () => abort.abort(),
    onEffect: async () => assert.fail("unexpected effect"),
  });
  assert.equal(requests, 3);
  assert.equal(observed, 1);
  assert.deepEqual(cursors, ["prefix"]);
});

for (const failResetCallback of [false, true]) {
  test(`reset then disconnect drops partial cursor and cold-recovers (${failResetCallback})`, async () => {
    const reducer = new ConversationStreamReducer();
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), 4000);
    let requests = 0;
    let bootstrap = 0;
    const cursors: Array<string | null> = [];
    const effects: string[] = [];
    const answer = custom("zebra.answer_committed", { model_call_id: "old", assistant_message: "kept" });
    const draft = (chunk_index: number, content_delta: string, last: boolean) => custom("zebra.stream.draft", { message_id: "message:new", generation_id: "generation", offset: 0, chunk_index, content_delta, last });
    const reset = `data: ${JSON.stringify(custom("zebra.stream.reset", {}))}\n\n`;
    const first = record("start", custom("zebra.stream.recovery_start", {})) + record("caught", custom("zebra.stream.recovery_complete", {})) + record("old", answer) + record("partial", draft(0, "prefix", false)) + reset;
    const historical = { type: "STATE_DELTA", delta: [{ op: "add", value: { effect_id: "finalized", status: "pending", execution_location: "client" } }] };
    try {
      await consumeClientEffectStream({
        fetchImpl: async (url, init) => {
          requests++;
          assert.ok(requests <= 2, "reset reconnect never completed");
          assert.match(String(url), /recovery=full/);
          assert.equal((init?.headers as Record<string, string>)["Last-Event-ID"], undefined);
          if (requests === 1) {
            let pulled = false;
            return new Response(new ReadableStream({ pull: controller => { if (pulled) controller.error(new Error("disconnect immediately after reset")); else { pulled = true; controller.enqueue(bytes(first)); } } }));
          }
          return new Response(record("restart", custom("zebra.stream.recovery_start", {})) + record("old-replay", answer) + record("historical-add", historical) + record("historical-remove", { type: "STATE_DELTA", delta: [{ op: "remove", path: "/pending_client_effects/finalized" }] }) + record("caught-again", custom("zebra.stream.recovery_complete", {})) + record("full-prefix", draft(0, "prefix", false)) + record("full-draft", draft(1, "suffix", true)));
        },
        streamUrl: "https://fixture.test/stream", headers: () => ({}), stopped: () => false, signal: abort.signal, streamVersion: 2,
        onObservation: async event => {
          reducer.observe(event);
          if (event.name === "zebra.stream.reset") {
            assert.deepEqual(reducer.snapshot().map(message => message.content), ["kept"]);
            if (failResetCallback) throw new Error("Host failed after resetting preview");
          }
        },
        onCursor: cursor => { cursors.push(cursor); if (cursor === "full-draft") abort.abort(); },
        onCursorRecovered: async () => { bootstrap++; }, onEffect: async effect => { effects.push(effect.effect_id); },
      });
    } finally { clearTimeout(timer); }
    assert.equal(requests, 2);
    assert.equal(bootstrap, 2);
    assert.deepEqual(effects, []);
    assert.equal(cursors.filter(cursor => cursor === null).length, 1);
    assert.deepEqual(reducer.snapshot().map(message => message.content), ["kept", "prefixsuffix"]);
    assert.equal(cursors.at(-1), "full-draft");
  });
}

test("reset does not pause same-connection live effects awaiting a nonexistent boundary", async () => {
  const abort = new AbortController();
  const effects: string[] = [];
  await consumeClientEffectStream({
    fetchImpl: async () => new Response(record("caught", custom("zebra.stream.recovery_complete", {})) + `data: ${JSON.stringify(custom("zebra.stream.reset", {}))}\n\n` + record("live-effect", { type: "STATE_DELTA", delta: [{ op: "add", value: { effect_id: "live", status: "pending", execution_location: "client" } }] })),
    streamUrl: "https://fixture.test/stream", headers: () => ({}), stopped: () => false, signal: abort.signal, streamVersion: 2,
    onObservation: async () => {}, onEffect: async effect => { effects.push(effect.effect_id); },
    onCursor: cursor => { if (cursor === "live-effect") abort.abort(); },
  });
  assert.deepEqual(effects, ["live"]);
});


for (const status of [400, 401, 403, 410]) {
  test(`terminal ${status} remains terminal when awaited Host teardown throws`, async () => {
    let requests = 0;
    let rejected = 0;
    const cursors: Array<string | null> = [];
    await consumeClientEffectStream({
      fetchImpl: async () => { requests++; assert.equal(requests, 1); return new Response("", { status }); },
      streamUrl: "https://fixture.test/stream", headers: () => ({}), stopped: () => false, signal: new AbortController().signal, streamVersion: 2,
      onObservation: async () => { throw new Error("Host teardown failed"); },
      onTerminalRejection: () => { rejected++; if (status === 410) throw new Error("Terminal hook failed"); }, onCursor: cursor => { cursors.push(cursor); },
      onEffect: async () => assert.fail("rejected authority dispatched effect"),
    });
    assert.equal(requests, 1);
    assert.equal(rejected, 1);
    assert.deepEqual(cursors, [null]);
  });
}

test("stream byte accounting encodes appended chunks, not the complete growing prefix", () => {
  const reducer = new ConversationStreamReducer();
  const original = TextEncoder.prototype.encode;
  let encodedCharacters = 0;
  TextEncoder.prototype.encode = function (input) {
    encodedCharacters += input?.length ?? 0;
    return original.call(this, input);
  };
  try {
    for (let offset = 0; offset < 32; offset++) {
      reducer.observe(custom("zebra.stream.draft", { message_id: "message:linear", generation_id: "g", offset, content_delta: "x".repeat(1024) }));
    }
    assert.equal(reducer.snapshot()[0]?.content.length, 32768);
    assert.ok(encodedCharacters <= 4 * 32768, `encoded ${encodedCharacters} characters for 32768 appended`);
  } finally {
    TextEncoder.prototype.encode = original;
  }
});

test("cached stream bytes handle split surrogate pairs, reset and generation replacement", () => {
  const reducer = new ConversationStreamReducer();
  for (let index = 0; index < 7; index++) {
    reducer.observe(custom("zebra.answer_committed", { model_call_id: `full-${index}`, assistant_message: "x".repeat(1_048_576) }));
  }
  const draft = (generation_id: string, offset: number, content_delta: string) => custom("zebra.stream.draft", { message_id: "message:edge", generation_id, offset, content_delta });
  reducer.observe(draft("g", 0, "x".repeat(1_048_572) + "\ud83d"));
  reducer.observe(draft("g", 1, "\ude00")); // The joined pair is four bytes, not two replacement characters.
  assert.throws(() => reducer.observe(draft("g", 2, "x")), /byte capacity/);
  reducer.observe(draft("new", 0, "small"));
  reducer.observe(custom("zebra.stream.reset", {}));
  assert.equal(reducer.snapshot().length, 7);
  reducer.observe(draft("reset", 0, "x".repeat(1_048_576)));
  reducer.observe(custom("zebra.stream.recovery_start", {}));
  assert.equal(reducer.snapshot().length, 0);
  reducer.observe(draft("fresh", 0, "ready"));
  assert.equal(reducer.snapshot()[0]?.content, "ready");
});

test("transport cursors distinguish replacement clear and content without accepting conflicting replay", () => {
  const reducer = new ConversationStreamReducer();
  const clear = { ...custom("zebra.message_replace", {
    message_id: "message:call", chunk_index: 0, content: "", last: true,
  }), streamCursor: "clear-cursor" };
  const content = { ...custom("zebra.message_replace", {
    message_id: "message:call", chunk_index: 0, content: "answer", last: true,
  }), streamCursor: "content-cursor" };
  reducer.observe(clear);
  reducer.observe(content);
  reducer.observe(content); // A lost Host ACK can replay only this exact frame.
  assert.equal(reducer.snapshot()[0]?.content, "answer");
  assert.throws(() => reducer.observe({ ...content, value: {
    message_id: "message:call", chunk_index: 0, content: "changed", last: true,
  } }), /Conflicting unacknowledged chunk/);
  assert.throws(() => reducer.observe({ ...content, value: {
    message_id: "message:other", chunk_index: 0, content: "answer", last: true,
  } }), /Conflicting unacknowledged chunk/);
});
