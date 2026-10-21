import assert from "node:assert/strict";
import { test } from "node:test";
import { createBffFetch } from "../src/bff_transport.ts";
import { ClientRuntimeError, ZebraClientRuntime } from "../src/index.ts";
import type { BffRuntimeClientConfig, ClientEffectWire } from "@zebra-agent/contracts";

const session = "11111111-1111-4111-8111-111111111111";
const task = "22222222-2222-4222-8222-222222222222";
const effectId = "44444444-4444-4444-8444-444444444444";
function config(fetchImpl: typeof fetch): BffRuntimeClientConfig {
  return { mode: "bff", baseUrl: "/api/agent/surfaces/public-binding", clientSessionId: session,
    controller: true, taskId: task, runId: "run-1", runBindingId: "33333333-3333-4333-8333-333333333333",
    clientBindingDigest: "b".repeat(64), actionContractDigests: { "app.ui.item.open": "a".repeat(64) }, fetchImpl };
}
function effect(): ClientEffectWire {
  const deadline = new Date(Date.now() + 60_000).toISOString();
  return { effect_id: effectId, task_id: task, run_id: "run-1", surface_instance_id: session,
    action_name: "app.ui.item.open", arguments: { itemId: "item-7" }, status: "pending", expected_ui_revision: 0,
    expires_at: deadline, deadline, idempotency_key: "effect-once", request_digest: "d".repeat(64),
    action_contract_digest: "a".repeat(64), capability_version: "a".repeat(64), client_binding_digest: "b".repeat(64) };
}

test("BFF mode executes and receipts without native secrets or a dummy credential", async () => {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  let actions = 0;
  const runtime = ZebraClientRuntime.fromConfig(config(async (input, init = {}) => {
    calls.push({ url: String(input), init });
    return Response.json(String(input).endsWith("/effects") ? { effects: [effect()] } : {});
  }));
  runtime.registry.mount("app.ui.item.open", () => { actions++; return { opened: true }; });
  try {
    await runtime.start();
    await runtime.poll();
    assert.equal(actions, 1);
    assert.equal(runtime.getStatus(), "ready");
    const receipt = calls.find((call) => call.url.endsWith("/receipts"));
    assert.ok(receipt);
    assert.equal(new Headers(receipt.init.headers).get("Idempotency-Key"), `sdk-receipt:${effectId}`);
    for (const call of calls) {
      for (const name of ["Authorization", "X-Zebra-Client-Session", "X-Zebra-Client-Fence"]) {
        assert.equal(new Headers(call.init.headers).has(name), false);
      }
      assert.equal(call.init.credentials, "same-origin");
      assert.equal(call.init.mode, "same-origin");
      assert.equal(call.init.redirect, "error");
      assert.equal(call.init.cache, "no-store");
      assert.ok(call.init.signal);
    }
  } finally { runtime.stop(); }
});

test("unavailable poll never becomes ready; recovery and current rejection update status", async () => {
  let status = 503;
  let calls = 0;
  const runtime = ZebraClientRuntime.fromConfig(config(async () => { calls++; return Response.json({ effects: [] }, { status }); }));
  const statuses: string[] = [];
  const unsubscribe = runtime.subscribeStatus(() => statuses.push(runtime.getStatus()));
  try {
    await runtime.start();
    assert.equal(runtime.getStatus(), "unavailable");
    status = 200;
    await runtime.poll();
    assert.equal(runtime.getStatus(), "ready");
    status = 401;
    await runtime.poll();
    assert.equal(runtime.getStatus(), "stopped");
    const before = calls;
    await runtime.poll();
    assert.equal(calls, before);
    assert.deepEqual(statuses, ["unavailable", "ready", "stopped"]);
  } finally { unsubscribe(); runtime.stop(); }
});

test("BFF mode rejects foreign prefixes and raw native credentials before I/O", () => {
  let calls = 0;
  const fetchImpl: typeof fetch = async () => { calls++; return Response.json({}); };
  for (const baseUrl of ["https://foreign.example", "//foreign.example", "/api/../foreign", "/api/%2e", "/api?a=b", "/api#secret"]) {
    assert.throws(() => ZebraClientRuntime.fromConfig({ ...config(fetchImpl), baseUrl }),
      (error: unknown) => error instanceof ClientRuntimeError && error.code === "invalid_bff_url");
  }
  const raw = { ...config(fetchImpl), sessionCredential: "native-secret-value" };
  assert.throws(() => ZebraClientRuntime.fromConfig(raw as unknown as BffRuntimeClientConfig),
    (error: unknown) => error instanceof ClientRuntimeError && error.code === "invalid_bff_config");
  assert.equal(calls, 0);
});

test("BFF observer cannot dispatch even when a pending controller effect is returned", async () => {
  let actions = 0;
  const cfg = { ...config(async () => Response.json({ effects: [effect()] })), controller: false };
  const runtime = ZebraClientRuntime.fromConfig(cfg);
  runtime.registry.mount("app.ui.item.open", () => { actions++; return {}; });
  try { await runtime.start(); assert.equal(actions, 0); } finally { runtime.stop(); }
});

test("BFF route/header/method/body guards refuse I/O beyond the fixed surface", async () => {
  let calls = 0;
  const fetchImpl = createBffFetch("/api/surfaces/surface-1", session, async () => { calls++; return Response.json({}); });
  const own = `/api/surfaces/surface-1/v1/client-sessions/${session}/effects`;
  for (const url of ["https://foreign.example" + own, own + "?x=1", own.replace(session, task), "/api/surfaces/surface-2/v1/client-sessions/" + session + "/effects"]) {
    await assert.rejects(() => fetchImpl(url));
  }
  for (const name of ["Authorization", "Cookie", "Origin", "Host", "X-Zebra-Client-Session", "X-Zebra-Client-Fence"]) {
    await assert.rejects(() => fetchImpl(own, { headers: { [name]: "forbidden" } }));
  }
  await assert.rejects(() => fetchImpl(own, { method: "DELETE" }));
  const post = own.replace("effects", "mount");
  await assert.rejects(() => fetchImpl(post, { method: "POST", body: "{}" }));
  await assert.rejects(() => fetchImpl(post, { method: "POST", headers: { "Content-Type": "application/json" }, body: "x".repeat(65_537) }));
  assert.equal(calls, 0);
});

test("bad/oversized pending response cannot become ready or dispatch a handler", async () => {
  for (const payload of [{}, { effects: "wrong" }, { effects: Array(51).fill(effect()) }, { effects: [{}] }, { effects: [{...effect(), effect_id: "not-native-id"}] }, { effects: [{...effect(), status: "succeeded"}] }, { padding: "x".repeat(1_048_577) }]) {
    let actions = 0;
    const runtime = ZebraClientRuntime.fromConfig(config(async () => Response.json(payload)));
    runtime.registry.mount("app.ui.item.open", () => { actions++; return {}; });
    try { await runtime.start(); assert.equal(runtime.getStatus(), "unavailable"); assert.equal(actions, 0); }
    finally { runtime.stop(); }
  }
});

test("only one poll is in flight and stopped runtime cannot be revived by a late response", async () => {
  let complete!: (value: Response) => void;
  let calls = 0;
  const cfg = { ...config(async () => { calls++; return new Promise<Response>(resolve => { complete = resolve; }); }), controller: false };
  const runtime = ZebraClientRuntime.fromConfig(cfg);
  const first = runtime.poll();
  await runtime.poll();
  assert.equal(calls, 1);
  runtime.stop();
  complete(Response.json({ effects: [] }));
  await first;
  assert.equal(runtime.getStatus(), "stopped");
});

test("start waits for the actual registered mount before polling", async () => {
  let complete!: (value: Response) => void;
  let polls = 0;
  const runtime = ZebraClientRuntime.fromConfig(config(async input => {
    if (String(input).endsWith("/mount")) return new Promise<Response>(resolve => { complete = resolve; });
    if (String(input).endsWith("/effects")) polls++;
    return Response.json({ effects: [] });
  }));
  void runtime.scheduleMount({ frontendAppId: "fixture-web", profileRevision: 1, profileDigest: "c".repeat(64), mountedActions: [] });
  const start = runtime.start();
  await Promise.resolve();
  assert.equal(polls, 0);
  assert.equal(runtime.getStatus(), "connecting");
  complete(Response.json({}));
  try { await start; assert.equal(polls, 1); assert.equal(runtime.getStatus(), "ready"); }
  finally { runtime.stop(); }
});

test("BFF config checks JSON types/unknown keys and exact native identifier/digest shapes", () => {
  const cfg = config(async () => Response.json({}));
  for (const fault of [{ clientSessionId: [session] }, { taskId: "foreign" }, { runId: 7 },
    { runBindingId: "binding" }, { clientBindingDigest: "b".repeat(64) + "\n" },
    { actionContractDigests: [] }, { hostGrant: "do-not-put-a-native-grant-in-the-browser" }]) {
    assert.throws(() => ZebraClientRuntime.fromConfig({ ...cfg, ...fault } as unknown as BffRuntimeClientConfig),
      (error: unknown) => error instanceof ClientRuntimeError && error.code === "invalid_bff_config");
  }
  assert.throws(() => ZebraClientRuntime.fromConfig({ ...cfg, mode: "bff-typo" } as unknown as BffRuntimeClientConfig),
    (error: unknown) => error instanceof ClientRuntimeError && error.code === "invalid_config");
});

test("observer heartbeat renews only Session without claiming a native Controller lease", async () => {
  const bodies: string[] = [];
  const runtime = ZebraClientRuntime.fromConfig({ ...config(async (input, init) => {
    if (String(input).endsWith("/heartbeat")) bodies.push(String(init?.body));
    return Response.json({ effects: [] });
  }), controller: false });
  try {
    await runtime.heartbeat();
    assert.deepEqual(bodies.map(body => JSON.parse(body)), [{}]);
  } finally { runtime.stop(); }
});
