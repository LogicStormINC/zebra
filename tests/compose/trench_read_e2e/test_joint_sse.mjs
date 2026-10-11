import assert from "node:assert/strict";
import test from "node:test";
import { createCapture } from "./joint_sse.mjs";

test("incremental UTF8 frames arrive before EOF without private body evidence", () => {
  const stream = { frames: [] };
  const calls = [];
  const capture = createCapture(stream, (frame) => calls.push(frame.cursor), () => 12);
  const body = Buffer.from('id: 1\ndata: {"type":"public_output","content":"部分结果","evidence_refs":["r"]}\n\nid: 2\ndata: {"answer_committed":true,"private_reasoning":"NEVER_EXPORT"}\n\n');
  for (let index = 0; index < body.length; index++) capture.feed(body.subarray(index, index + 1));
  assert.deepEqual(calls, [1, 2]);
  assert.equal(stream.frames[0].coverage_qualified, true);
  assert.equal(stream.frames[0].observer_receipt_node_ms, 12);
  assert.ok(!JSON.stringify(stream).includes("NEVER_EXPORT"));
  capture.finish();
});

test("EOF cannot silently accept an incomplete final", () => {
  const capture = createCapture({ frames: [] }, () => {});
  capture.feed(Buffer.from('id: 1\ndata: {"answer_committed":true}'));
  assert.throws(() => capture.finish(), /truncated/);
});

test("unpositioned observation problem is not a final", () => {
  const capture = createCapture({ frames: [] }, () => {});
  assert.throws(() => capture.feed(Buffer.from('data: {"type":"error"}\n\n')), /unpositioned/);
});

test("unframed provider silence cannot grow the buffer", () => {
  const capture = createCapture({ frames: [] }, () => {});
  assert.throws(() => capture.feed(Buffer.alloc(65537, 65)), /buffer ceiling/);
});
