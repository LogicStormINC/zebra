import assert from "node:assert/strict";
import test from "node:test";
import { startMediaObserver } from "./mediafixtures/browser_media_observer.mjs";

test("failed image decode retains a static stage without exporting its exception", async () => {
  const image = { first() { return this; }, async scrollIntoViewIfNeeded() {},
    async evaluate() { throw new Error("private-cookie-provider-body"); } };
  const page = { waitForResponse: () => new Promise(() => {}), on() {}, off() {},
    async route() {}, async unroute() {}, locator: () => image };
  const observer = await startMediaObserver({ page, caseId: "image", guard: async () => {},
    config: { base_url: "https://localhost", timeout_ms: 1000 } });
  observer.onFrame({}, {});
  await assert.rejects(observer.finish({ frames: [] }), /live media\/revision observation failed/);
  const evidence = observer.evidence();
  assert.equal(evidence.failure_stage, "image_decode");
  assert.equal(evidence.observation_failed, true);
  assert.equal(JSON.stringify(evidence).includes("private-cookie"), false);
  assert.equal(evidence.fault_aborted, false);
});

test("fault target uses the genuine import receipt before the present label is mounted", async () => {
  let handler, aborted = false;
  const page = { waitForResponse: () => new Promise(() => {}), on() {},
    async route(_, callback) { handler = callback; },
    locator: () => ({ async count() { return 0; } }) };
  const observer = await startMediaObserver({ page, caseId: "image", guard: async () => {},
    config: { base_url: "https://localhost", timeout_ms: 1000, media_fixture: { event_id: "fixture" } } });
  const artifactId = "/api/trench-ai/assets/123e4567-e89b-12d3-a456-426614174000/5e23c02e-ca10-4851-b575-a3080a4b8f34";
  observer.onFrame({}, { answer_committed: true, content_parts: [{ type: "image", artifactId,
    fileName: "fixture-image-2.jpg" }] });
  await handler({ request: () => ({ url: () => `https://localhost${artifactId}/preview`,
    method: () => "GET", resourceType: () => "image" }), async abort() { aborted = true; } });
  assert.equal(aborted, true);
  assert.equal(observer.evidence().fault_aborted, true);
});
