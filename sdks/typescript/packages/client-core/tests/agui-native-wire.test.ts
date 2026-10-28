/** Cloud encoder -> real loopback HTTP -> SDK, without a business Host runtime. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { once } from "node:events";
import test from "node:test";
import { ConversationStreamReducer } from "../src/conversation_stream.ts";
import { consumeClientEffectStream } from "../src/sse_stream.ts";

const fixturePath = process.env.ZEBRA_LONG_WIRE_FILE;
assert.ok(fixturePath, "run tests/conformance/agui_long_session/run.sh to generate actual Cloud wire");
const fixture = JSON.parse(readFileSync(fixturePath, "utf8")) as {
  frames: { token: string; wire: string }[];
  partial_frames: { token: string; wire: string }[];
  answer_sha256: string;
  run_id: string;
};
const notice = (name: string) => `data: ${JSON.stringify({ type: "CUSTOM", name, value: {} })}\n\n`;

for (const partial of [false, true]) {
  test(`cold SDK restores native large answer and ${partial ? "partial" : "complete"} terminal`, { timeout: 10000 }, async () => {
    const frames = partial ? fixture.partial_frames : fixture.frames;
    assert.ok(frames.length > 50);
    const requests: { method?: string; url?: string; cursor?: string }[] = [];
    const server = createServer((req, res) => {
      requests.push({ ...(req.method ? { method: req.method } : {}), ...(req.url ? { url: req.url } : {}),
        ...(typeof req.headers["last-event-id"] === "string" ? { cursor: req.headers["last-event-id"] } : {}) });
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      res.write(notice("zebra.stream.recovery_start"));
      // A transient reset must not discard an in-progress canonical answer/tool prefix.
      frames.forEach((frame, index) => {
        res.write(frame.wire);
        if (index % 17 === 3) res.write(notice("zebra.stream.reset"));
      });
      res.end();
    });
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    const address = server.address();
    assert.ok(address && typeof address !== "string");
    const abort = new AbortController();
    const deadline = setTimeout(() => abort.abort(), 4000);
    const reducer = new ConversationStreamReducer();
    let observationError: unknown;
    let terminal: Record<string, unknown> | undefined;
    let assessment: unknown;
    let toolResults = 0;
    try {
      await consumeClientEffectStream({
        fetchImpl: fetch,
        streamUrl: `http://127.0.0.1:${address.port}/tasks/test/ag-ui/events`,
        headers: () => ({}), stopped: () => false, signal: abort.signal, streamVersion: 2,
        // A persisted cursor alone is insufficient to reconstruct a new observer.
        initialEventId: frames.at(-1)!.token,
        onEffect: async () => assert.fail("recovery must not execute historical effects"),
        onObservation: async event => {
          try { reducer.observe(event); } catch (error) {
            observationError ??= error; abort.abort(); return;
          }
          if (event.type === "TOOL_CALL_RESULT") toolResults++;
          if (event.name === "zebra.answer_committed") {
            assessment = (event.value as { delivery_assessment: { status: string } }).delivery_assessment.status;
          }
          // Consumers own the observation lifecycle, using decoded canonical events.
          if (event.type === "RUN_FINISHED" || event.type === "RUN_ERROR") {
            terminal = event as Record<string, unknown>;
            abort.abort();
          }
        },
      });
      if (observationError) throw observationError;
      assert.deepEqual(requests, [{ method: "GET", url: "/tasks/test/ag-ui/events?recovery=full" }]);
      assert.equal(terminal?.runId, fixture.run_id);
      assert.equal((terminal?.outcome as { type: string }).type, partial ? "interrupt" : "success");
      assert.equal(assessment, partial ? "partial" : "complete");
      assert.equal(toolResults, 1);
      const messages = reducer.snapshot();
      assert.equal(messages.length, 1);
      assert.equal(messages[0]?.presentation, "committed");
      assert.equal(createHash("sha256").update(messages[0]!.content).digest("hex"), fixture.answer_sha256);
    } finally {
      clearTimeout(deadline);
      abort.abort();
      server.closeAllConnections();
      await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
    }
  });
}
