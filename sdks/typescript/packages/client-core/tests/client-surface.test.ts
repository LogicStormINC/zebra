import assert from "node:assert/strict";
import test from "node:test";
import { mountClientSurface } from "../src/client_surface.ts";
const taskId = "11111111-1111-4111-8111-111111111111";
const mount = {client_session_id: "22222222-2222-4222-8222-222222222222", frontend_app_id: "web",
  profile_revision: 1, profile_digest: "a".repeat(64), mounted_readables: [],
  mounted_actions: ["app.ui.open"], ui_revision: 1, mounted_at: "2026-10-15T00:00:00Z"};
const binding = {binding_id: "33333333-3333-4333-8333-333333333333", binding_digest: "b".repeat(64),
  binding_revision: 1, allowed_actions: ["app.ui.open"], controller: true, controller_fence_token: "f".repeat(64)};
for (const version of [1, 0, undefined, true, "1"]) {
  test(`explicit capability selects request count: ${String(version)}`, async () => {
    const calls: {path: string; body: unknown}[] = [];
    const response = await mountClientSurface({taskId, runId: "run-1", mount,
      taskCapabilityScope: ["app.ui.open"], capabilities: {client_surface_contract_version: version},
      request: async (path, body) => {calls.push({path, body}); return path.endsWith("/mount")
        ? {mounted_snapshot_digest: "a".repeat(64), ui_revision: 1}
        : {...binding, mounted_snapshot_digest: "a".repeat(64), ui_revision: 1};},
    });
    assert.equal(calls.length, version === 1 ? 1 : 2);
    assert.equal(response.binding_id, binding.binding_id);
    if (version === 1) assert.deepEqual(calls[0]?.body, {mount, task_capability_scope: ["app.ui.open"], controller: true});
    else assert.equal(calls[0]?.path, `/v1/client-sessions/${mount.client_session_id}/mount`);
  });
}
test("advertised failure never falls back or reopens", async () => {
  const paths: string[] = [];
  await assert.rejects(mountClientSurface({taskId, runId: "run", mount, taskCapabilityScope: [],
    capabilities: {client_surface_contract_version: 1}, request: async (path) => {paths.push(path); throw new Error("response lost");},
  }), /response lost/);
  assert.deepEqual(paths, [`/v1/tasks/${taskId}/runs/run/client-surface`]);
});
test("legacy mount failure prevents binding", async () => {
  let count = 0;
  await assert.rejects(mountClientSurface({taskId, runId: "run", mount, taskCapabilityScope: [],
    capabilities: {}, request: async () => {count++; throw new Error("mount rejected");},
  }), /mount rejected/);
  assert.equal(count, 1);
});
test("incomplete response is unusable", async () => {
  await assert.rejects(mountClientSurface({taskId, runId: "run", mount, taskCapabilityScope: [],
    capabilities: {client_surface_contract_version: 1}, request: async () => ({binding_id: "partial"}),
  }), /invalid client surface response/);
});
