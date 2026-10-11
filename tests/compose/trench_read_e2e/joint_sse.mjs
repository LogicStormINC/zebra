// Incremental native browser SSE parsing, with no private bodies retained in evidence.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { StringDecoder } from "node:string_decoder";

export function createCapture(stream, onFrame, now = performance.now.bind(performance)) {
  const decoder = new StringDecoder("utf8");
  let pending = "";
  let bytes = 0;
  const feed = (chunk) => {
    bytes += chunk.byteLength;
    assert.ok(bytes <= 1048576, "native SSE evidence byte ceiling");
    pending += decoder.write(chunk);
    let boundary;
    while ((boundary = pending.match(/\r?\n\r?\n/))) {
      const block = pending.slice(0, boundary.index);
      pending = pending.slice(boundary.index + boundary[0].length);
      const cursor = block.match(/^id:\s*(\d+)$/m)?.[1];
      const data = block.split(/\r?\n/).filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart()).join("\n");
      if (!data) continue;
      assert.ok(cursor, "unpositioned problem is not successful streaming");
      const event = JSON.parse(data);
      const frame = { cursor: Number(cursor), observer_receipt_node_ms: now() };
      for (const key of ["type", "event_id", "sequence", "message_id", "output_id", "kind", "phase",
        "answer_committed", "meaningful", "evidence_basis", "origin", "policy_version"]) {
        if (event[key] !== undefined) frame[key] = event[key];
      }
      if (event.type === "public_output") {
        assert.ok(typeof event.content === "string" && event.content.length <= 4000);
        frame.content_sha256 = createHash("sha256").update(event.content).digest("hex");
        frame.coverage_qualified = /部分|覆盖|范围|sample|coverage|scope/i.test(event.content);
        frame.evidence_refs = event.evidence_refs;
      }
      stream.frames.push(frame);
      assert.ok(stream.frames.length <= 256, "native SSE evidence frame ceiling");
      onFrame(frame, event);
    }
    assert.ok(pending.length <= 65536, "native SSE unframed buffer ceiling");
  };
  return { feed, bytes: () => bytes, finish: () => {
    pending += decoder.end();
    assert.equal(pending.trim(), "", "truncated native SSE frame");
  } };
}
