import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { EventType, type BaseEvent } from "@ag-ui/core";
import { lastValueFrom, toArray } from "rxjs";
import { standardAgUiEvents } from "../src/agui_events.ts";

const binding = { threadId: "thread", runId: "run" };
const start = { type: "RUN_STARTED", ...binding };
const end = { type: "RUN_FINISHED", ...binding };
const collect = (events: unknown[]) => lastValueFrom(standardAgUiEvents(events, binding).pipe(toArray()));

test("official taxonomy matches all 31 frozen schema union members", () => {
  const catalog = JSON.parse(readFileSync(new URL("../../../../../tests/conformance/agui_contract/event-catalog.json", import.meta.url), "utf8")) as { type: string }[];
  assert.equal(catalog.length, 31);
  assert.deepEqual(Object.values(EventType).sort(), catalog.map(e => e.type).sort());
});

test("enforcement strips unknown fields, drops unknown types and rejects malformed known fields", async () => {
  const events = await collect([start, { type: "FUTURE" }, { type: "CUSTOM", name: "hello", value: false, future: true }, end]);
  assert.deepEqual(events.map(e => e.type), ["RUN_STARTED", "CUSTOM", "RUN_FINISHED"]);
  assert.equal("future" in events[1]!, false);
  for (const bad of [
    { type: "TEXT_MESSAGE_CONTENT", messageId: "m", delta: 5 },
    { type: "TEXT_MESSAGE_CHUNK", messageId: "m", role: "bogus", delta: "x" }, null, {},
  ]) await assert.rejects(collect([start, bad, end]));
});

test("official chunks equal explicit text, tool and reasoning events", async () => {
  for (const [chunk, explicit] of [
    [[{ type: "TEXT_MESSAGE_CHUNK", messageId: "m", delta: "ab" }], [
      { type: "TEXT_MESSAGE_START", messageId: "m", role: "assistant" },
      { type: "TEXT_MESSAGE_CONTENT", messageId: "m", delta: "ab" }, { type: "TEXT_MESSAGE_END", messageId: "m" },
    ]],
    [[{ type: "TOOL_CALL_CHUNK", toolCallId: "t", toolCallName: "lookup", delta: "{}" }], [
      { type: "TOOL_CALL_START", toolCallId: "t", toolCallName: "lookup" },
      { type: "TOOL_CALL_ARGS", toolCallId: "t", delta: "{}" }, { type: "TOOL_CALL_END", toolCallId: "t" },
    ]],
    [[{ type: "REASONING_MESSAGE_CHUNK", messageId: "q", delta: "why" }], [
      { type: "REASONING_MESSAGE_START", messageId: "q", role: "reasoning" },
      { type: "REASONING_MESSAGE_CONTENT", messageId: "q", delta: "why" }, { type: "REASONING_MESSAGE_END", messageId: "q" },
    ]],
  ] as const) assert.deepEqual(await collect([start, ...chunk, end]), await collect([start, ...explicit, end]));
});

test("binding and lifecycle reject invalid stream before application", async () => {
  for (const foreign of [
    { ...start, threadId: "other" }, { ...start, runId: "other" }, { ...end, runId: "other" },
  ]) await assert.rejects(collect([start, foreign]));
  await assert.rejects(collect([{ type: "TEXT_MESSAGE_CONTENT", messageId: "m", delta: "x" }]));
  await assert.rejects(collect([start, end, { type: "CUSTOM", name: "late", value: null }]));
});

test("every frozen event type has an actual positive official schema example", async () => {
  const { enforceEvents } = await import("@ag-ui/client");
  const { from } = await import("rxjs");
  const examples = [start, end, { type: "RUN_ERROR", message: "failed" },
    { type: "STEP_STARTED", stepName: "s" }, { type: "STEP_FINISHED", stepName: "s" },
    { type: "TEXT_MESSAGE_START", messageId: "m", role: "assistant" },
    { type: "TEXT_MESSAGE_CONTENT", messageId: "m", delta: "x" }, { type: "TEXT_MESSAGE_END", messageId: "m" },
    { type: "TEXT_MESSAGE_CHUNK", messageId: "m", delta: "x" },
    { type: "TOOL_CALL_START", toolCallId: "t", toolCallName: "lookup" },
    { type: "TOOL_CALL_ARGS", toolCallId: "t", delta: "{}" }, { type: "TOOL_CALL_END", toolCallId: "t" },
    { type: "TOOL_CALL_CHUNK", toolCallId: "t", toolCallName: "lookup", delta: "{}" },
    { type: "TOOL_CALL_RESULT", messageId: "r", toolCallId: "t", role: "tool", content: "done" },
    { type: "STATE_SNAPSHOT", snapshot: null }, { type: "STATE_DELTA", delta: [] },
    { type: "MESSAGES_SNAPSHOT", messages: [] },
    { type: "ACTIVITY_SNAPSHOT", messageId: "a", activityType: "progress", content: {} },
    { type: "ACTIVITY_DELTA", messageId: "a", activityType: "progress", patch: [] },
    { type: "RAW", event: { native: true } }, { type: "CUSTOM", name: "extension", value: null },
    { type: "REASONING_START", messageId: "span" }, { type: "REASONING_END", messageId: "span" },
    { type: "REASONING_MESSAGE_START", messageId: "q", role: "reasoning" },
    { type: "REASONING_MESSAGE_CONTENT", messageId: "q", delta: "x" }, { type: "REASONING_MESSAGE_END", messageId: "q" },
    { type: "REASONING_MESSAGE_CHUNK", messageId: "q", delta: "x" },
    { type: "REASONING_ENCRYPTED_VALUE", subtype: "message", entityId: "q", encryptedValue: "opaque" },
    { type: "SUBAGENT_STARTED", subagentRunId: "child", name: "research" },
    { type: "SUBAGENT_FINISHED", subagentRunId: "child" },
    { type: "SUBAGENT_ERROR", subagentRunId: "child", message: "child failed" },
  ];
  const accepted = await lastValueFrom(from(examples as BaseEvent[]).pipe(enforceEvents(), toArray()));
  assert.deepEqual(accepted, examples);
  assert.deepEqual(accepted.map(e => e.type).sort(), Object.values(EventType).sort());
});


test("unknown scope fields are stripped/dropped before binding checks", async () => {
  const events = await collect([start,
    { type: "FUTURE", threadId: "foreign", runId: "foreign" },
    { type: "TEXT_MESSAGE_CHUNK", messageId: "m", delta: "x", threadId: "foreign", runId: "foreign" },
    { type: "CUSTOM", name: "x", value: {}, runId: "foreign" }, end]);
  assert.deepEqual(events.map(e => e.type), ["RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END", "CUSTOM", "RUN_FINISHED"]);
  assert.ok(events.slice(1, -1).every(e => !("runId" in e) && !("threadId" in e)));
  await assert.rejects(collect([{ ...start, input: { threadId: "foreign", runId: "run", messages: [] } }]));
  await assert.rejects(collect([start, end, start]), /one RUN_STARTED/);
});

test("each observable subscription owns its lifecycle and chunk state", async () => {
  const events = standardAgUiEvents([start, { type: "TEXT_MESSAGE_CHUNK", messageId: "m", delta: "x" }, end], binding);
  assert.deepEqual(await lastValueFrom(events.pipe(toArray())), await lastValueFrom(events.pipe(toArray())));
});
