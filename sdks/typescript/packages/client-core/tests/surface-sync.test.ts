import assert from "node:assert/strict";
import { test } from "node:test";
import { ZebraClientRuntime, MountedActionRegistry, prepareInitialClientSurface } from "../src/index.ts";

const session = "11111111-1111-4111-8111-111111111111";
const task = "22222222-2222-4222-8222-222222222222";
const binding = "33333333-3333-4333-8333-333333333333";
const id = "44444444-4444-4444-8444-444444444444";
const action = "app.ui.item.open";
const options = { frontendAppId: "fixture-web", profileRevision: 1, profileDigest: "c".repeat(64), mountedActions: [action] };
const metadata = (revision: number) => ({ client_surface_metadata_contract_version: 1,
  profile_digest: options.profileDigest, ui_revision: revision, mounted_snapshot_digest: "e".repeat(64),
  binding_mounted_snapshot_digest: "e".repeat(64), binding_id: binding, binding_revision: revision,
  binding_digest: String(revision).repeat(64), allowed_actions: [action],
  action_contract_digests: { [action]: "a".repeat(64) }, controller: true });
function config(fetchImpl: typeof fetch) {
  return { mode: "bff" as const, surfaceMetadataVersion: 1 as const, baseUrl: "/api/agent/surface", clientSessionId: session,
    controller: true, taskId: task, runId: "run-1", runBindingId: binding, clientBindingDigest: "b".repeat(64),
    actionContractDigests: { [action]: "a".repeat(64) }, initialUiRevision: 0, fetchImpl };
}
function effect(revision: number) {
  const deadline = new Date(Date.now() + 60_000).toISOString();
  return { effect_id: id, task_id: task, run_id: "run-1", surface_instance_id: session,
    action_name: action, arguments: {}, status: "pending" as const, expected_ui_revision: revision,
    expires_at: deadline, deadline, idempotency_key: "one", request_digest: "d".repeat(64),
    action_contract_digest: "a".repeat(64), capability_version: "a".repeat(64), client_binding_digest: String(revision).repeat(64) };
}

test("native public mount metadata replaces stale binding before dispatch", async () => {
  let count = 0;
  const rt = new ZebraClientRuntime(config(async (input, init) => Response.json(String(input).endsWith("/mount")
    ? metadata(JSON.parse(String(init?.body)).ui_revision) : { effects: [effect(1)] })) as never);
  rt.registry.mount(action, () => { count++; return {}; });
  try { await rt.mount(options); await rt.poll(); assert.equal(count, 1); assert.equal(rt.isStopped, false); }
  finally { rt.disconnect(); }
});

test("mount pauses dispatch and applies strict public response only after completion", async () => {
  let complete!: (response: Response) => void;
  let count = 0;
  const rt = ZebraClientRuntime.fromConfig(config(async input => String(input).endsWith("/mount")
    ? new Promise(resolve => { complete = resolve; }) : Response.json({ effects: [effect(1)] })));
  rt.registry.mount(action, () => { count++; return {}; });
  try {
    const mount = rt.mount(options); await new Promise(resolve => setTimeout(resolve, 0));
    await rt.poll(); assert.equal(count, 0); assert.equal(rt.getStatus(), "connecting");
    complete(Response.json(metadata(1))); await mount; await rt.poll(); assert.equal(count, 1);
  } finally { rt.disconnect(); }
});

test("secret-bearing or inconsistent mount responses stop without release or retry", async () => {
  for (const change of [ { controller_fence_token: "server-only" }, { ui_revision: 99 },
    { binding_mounted_snapshot_digest: "f".repeat(64) }, { action_contract_digests: {} }, { binding_id: task } ]) {
    const calls: string[] = [];
    const rt = ZebraClientRuntime.fromConfig(config(async input => { calls.push(String(input)); return Response.json({ ...metadata(1), ...change }); }));
    await assert.rejects(rt.mount(options)); assert.equal(rt.isStopped, true);
    assert.equal(calls.length, 1); assert.ok(calls[0]?.endsWith("/mount"));
  }
});

test("mount waits for an executing action and its receipt before changing revision", async () => {
  const order: string[] = []; let finish!: () => void;
  const rt = ZebraClientRuntime.fromConfig(config(async (input, init) => {
    const path = String(input); order.push(path.endsWith("/mount") ? "mount" : "receipt");
    return Response.json(path.endsWith("/mount") ? metadata(JSON.parse(String(init?.body)).ui_revision) : {});
  }));
  rt.registry.mount(action, async () => { await new Promise<void>(resolve => { finish = resolve; }); return { done: true }; });
  try {
    await rt.mount(options); const executing = rt.runEffect(effect(1));
    const next = rt.mount(options); await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(rt.uiRevision.current, 1); assert.deepEqual(order, ["mount"]);
    finish(); await executing; await next; assert.deepEqual(order, ["mount", "receipt", "mount"]);
    assert.equal(rt.uiRevision.current, 2);
  } finally { rt.disconnect(); }
});

test("unresolved persisted receipts and inflight markers survive and block native remount", async () => {
  for (const state of [{ pendingReceipts: [{ effect_id: id, request_digest: "d".repeat(64), status: "succeeded", result: { opened: true } }] }, { inflightEffects: [id] }]) {
    const saved = JSON.stringify(state); let current = saved; let calls = 0;
    const storage = { getItem: () => current, setItem: (_: string, v: string) => { current = v; } } as unknown as Storage;
    const rt = ZebraClientRuntime.fromConfig({ ...config(async () => { calls++; return Response.json(metadata(1)); }), storage });
    await assert.rejects(rt.mount(options), /reconcile/); assert.equal(calls, 0); assert.equal(current, saved);
    assert.equal(rt.isStopped, true);
  }
});

test("initial synchronized runtime cannot dispatch before a successful SDK mount", async () => {
  let calls = 0;
  const rt = ZebraClientRuntime.fromConfig(config(async () => { calls++; return Response.json({ effects: [effect(1)] }); }));
  try { await rt.start(); await rt.poll(); await rt.runEffect(effect(1)); assert.equal(calls, 0); assert.equal(rt.getStatus(), "connecting"); }
  finally { rt.disconnect(); }
});

test("new binding is used after same-action remount; old binding cannot execute", async () => {
  let count = 0;
  const rt = ZebraClientRuntime.fromConfig(config(async (input, init) => Response.json(String(input).endsWith("/mount") ? metadata(JSON.parse(String(init?.body)).ui_revision) : {})));
  rt.registry.mount(action, () => { count++; return {}; });
  try {
    await rt.mount(options); await rt.mount(options); await rt.runEffect(effect(2)); assert.equal(count, 1);
    await rt.runEffect({ ...effect(1), effect_id: task }); assert.equal(count, 1); assert.equal(rt.isStopped, true);
  } finally { rt.disconnect(); }
});

test("mount response parsing is bounded, exact and no late success revives a disconnected runtime", async () => {
  for (const body of ["x".repeat(65_537), JSON.stringify({ ...metadata(1), controller: false }), JSON.stringify({ ...metadata(1), binding_revision: 0 })]) {
    const rt = ZebraClientRuntime.fromConfig(config(async () => new Response(body)));
    await assert.rejects(rt.mount(options)); assert.equal(rt.isStopped, true);
  }
  let done!: (response: Response) => void;
  const rt = ZebraClientRuntime.fromConfig(config(async () => new Promise(resolve => { done = resolve; })));
  const mount = rt.mount(options); await new Promise(resolve => setTimeout(resolve, 0)); rt.disconnect();
  done(Response.json(metadata(1))); await mount; assert.equal(rt.getStatus(), "stopped");
});

test("adopt original atomic Surface without any network or Controller rotation", async () => {
  let requests=0;
  const deps={...config(async()=>{requests++;throw Error('must not mount');}),initialUiRevision:1,clientBindingDigest:'1'.repeat(64)};
  const runtime=new ZebraClientRuntime(deps);
  runtime.registry.mount(action,()=>({opened:true}));
  runtime.adoptInitialSurface(metadata(1), options);
  assert.equal(requests,0);
  assert.throws(()=>runtime.adoptInitialSurface(metadata(1),options));
  const mismatch=new ZebraClientRuntime(deps);mismatch.registry.mount(action,()=>({}));
  assert.throws(()=>mismatch.adoptInitialSurface(metadata(2),options));
  assert.throws(()=>mismatch.adoptInitialSurface({...metadata(1),controller_fence_token:'forged'},options));
  const empty=new ZebraClientRuntime(deps);assert.throws(()=>empty.adoptInitialSurface(metadata(1),options));
});

test("initial preparation freezes registered names and Readable JSON before dispatch", () => {
 const registry=new MountedActionRegistry();registry.mount(action,()=>({opened:true}));
 const values={"app.ui.route":{route:"/item/1"}};
 const prepared=prepareInitialClientSurface(registry,values);values["app.ui.route"].route="/item/2";
 assert.deepEqual(prepared.input.state,{"app.ui.route":{route:"/item/1"}});
 assert.deepEqual(prepared.mountedActions,[action]);
 assert.throws(()=>prepareInitialClientSurface(registry,{"app.ui.route":{n:NaN}}));
 assert.throws(()=>prepareInitialClientSurface(registry,{"app.ui.route":{n:1.5}}));
 assert.throws(()=>prepareInitialClientSurface(registry,{"invalid":{}}));
});
