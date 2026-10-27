import assert from "node:assert/strict";
import { test } from "node:test";
import { ZebraClientRuntime } from "../src/index.ts";
import { nativeReadableCommand, copyReadableJson } from "../src/readable_commands.ts";
const session = "11111111-1111-4111-8111-111111111111", task = "22222222-2222-4222-8222-222222222222", binding = "33333333-3333-4333-8333-333333333333";
const name = "app.ui.route";
const options = { frontendAppId: "fixture-web", profileRevision: 1, profileDigest: "c".repeat(64), mountedActions: [], mountedReadables: [name] };
const metadata = (revision: number) => ({ client_surface_metadata_contract_version: 1 as const, profile_digest: options.profileDigest, ui_revision: revision, mounted_snapshot_digest: "e".repeat(64), binding_mounted_snapshot_digest: "e".repeat(64), binding_id: binding, binding_revision: revision, binding_digest: String(revision).repeat(64), allowed_actions: [], action_contract_digests: {}, controller: false });
const command = { action: "run" as const, expectedRevision: 2, idempotencyKey: "readable-1", input: { messages: [] } };
function config(fetchImpl: typeof fetch) { return { mode: "bff" as const, clientStateVersion: 1 as const, surfaceMetadataVersion: 1 as const, baseUrl: "/api/agent/surface", clientSessionId: session, controller: false, taskId: task, runId: "run-1", runBindingId: binding, clientBindingDigest: "b".repeat(64), actionContractDigests: {}, initialUiRevision: 0, fetchImpl }; }
test("values are copied per command; native authority remains BFF-owned; empty clears", async () => {
 const sent: { body: any; init: RequestInit }[] = [];
 const rt = ZebraClientRuntime.fromConfig(config(async (url, init) => { const body = JSON.parse(String(init?.body)); if (String(url).endsWith("/mount")) return Response.json(metadata(body.ui_revision)); sent.push({ body, init: init! }); return Response.json({ status: "accepted", commandId: "44444444-4444-4444-8444-444444444444" }); }));
 try {
  const value = { route: "/items", nested: { id: 1 } }; rt.mountReadable(name, value); value.nested.id = 9;
  await rt.mount(options); await rt.submitReadableCommand(command);
  assert.deepEqual(sent[0]?.body.input.state, { [name]: { route: "/items", nested: { id: 1 } } }); assert.equal(sent[0]?.body.input.forwardedProps, undefined);
  assert.equal(new Headers(sent[0]?.init.headers).get("idempotency-key"), "readable-1"); assert.equal(sent[0]?.init.credentials, "same-origin");
  rt.updateReadable(name, { route: "/other" }); await rt.scheduleMount(options); await rt.submitReadableCommand({ ...command, idempotencyKey: "next" });
  assert.equal(sent[0]?.body.input.state[name].route, "/items"); assert.equal(sent[1]?.body.input.state[name].route, "/other");
  rt.unmountReadable(name); await rt.scheduleMount({ ...options, mountedReadables: [] }); await rt.submitReadableCommand({ ...command, idempotencyKey: "clear" }); assert.deepEqual(sent[2]?.body.input.state, {});
 } finally { rt.disconnect(); }
});
test("command waits for queued mount and remount drains in-flight command", async () => {
 const order: string[] = []; let complete!: (response: Response) => void;
 const rt = ZebraClientRuntime.fromConfig(config(async (url, init) => { if (String(url).endsWith("/mount")) { order.push("mount"); return Response.json(metadata(JSON.parse(String(init?.body)).ui_revision)); } order.push("command"); return new Promise(resolve => { complete = resolve; }); }));
 try { rt.mountReadable(name, {}); const mounted = rt.scheduleMount(options); const pending = rt.submitReadableCommand(command); await mounted; await new Promise(r => setTimeout(r, 0)); assert.deepEqual(order, ["mount", "command"]); const next = rt.mount(options); await new Promise(r => setTimeout(r, 0)); assert.deepEqual(order, ["mount", "command"]); complete(Response.json({ status: "accepted", commandId: "44444444-4444-4444-8444-444444444444" })); await pending; await next; assert.deepEqual(order, ["mount", "command", "mount"]); } finally { rt.disconnect(); }
});
test("duplicate/missing registration, negotiation, unsafe JSON and authority fields rejected", async () => {
 let calls = 0; const rt = ZebraClientRuntime.fromConfig(config(async () => { calls++; return Response.json(metadata(1)); }));
 try { rt.mountReadable(name, {}); assert.throws(() => rt.mountReadable(name, {}), /already/); assert.throws(() => rt.updateReadable("foreign.name", {})); await assert.rejects(rt.submitReadableCommand(command)); assert.equal(calls, 0); await rt.mount(options);
 for (const input of [{ state: {} }, { forwardedProps: {} }, { tools: [] }, { messages: [], hidden: "x" }]) await assert.rejects(rt.submitReadableCommand({ ...command, input } as never)); assert.equal(calls, 1); } finally { rt.disconnect(); }
 for (const version of [0, true, 2]) assert.throws(() => ZebraClientRuntime.fromConfig({ ...config(fetch), clientStateVersion: version } as never));
 assert.throws(() => ZebraClientRuntime.fromConfig({ ...config(fetch), surfaceMetadataVersion: undefined } as never));
 for (const value of [NaN, Infinity, undefined, new Date(), () => {}, "\u0000", "\ud800", { value: undefined }, Array(4), { nested: [NaN] }]) assert.throws(() => copyReadableJson({ value }));
 const cyclic: any = {}; cyclic.loop = cyclic; assert.throws(() => copyReadableJson(cyclic)); assert.throws(() => copyReadableJson({ values: Array(4096).fill(0) })); assert.throws(() => copyReadableJson({ text: "x".repeat(65537) })); assert.deepEqual(copyReadableJson({ text: "页面 😀", small: 1e-100 }), { text: "页面 😀", small: 1e-100 });
});
test("unknown/malformed response never retries; CAS rejection remains explicit", async () => {
 for (const response of [() => Response.json({ status: "accepted" }), () => Response.json({ status: "accepted", commandId: "-".repeat(36) }), () => { throw new Error("network secret"); }, () => new Response("bad"), () => Response.json({}, { status: 503 }), () => Response.json({ status: "accepted", commandId: "44444444-4444-4444-8444-444444444444", credential: "secret" })]) {
 let calls = 0; const rt = ZebraClientRuntime.fromConfig(config(async (url, init) => String(url).endsWith("/mount") ? Response.json(metadata(JSON.parse(String(init?.body)).ui_revision)) : (calls++, response()))); rt.mountReadable(name, {}); await rt.mount(options); await assert.rejects(rt.submitReadableCommand(command), /unknown/); assert.equal(calls, 1); assert.equal(rt.isStopped, true); }
 const rt = ZebraClientRuntime.fromConfig(config(async (url, init) => String(url).endsWith("/mount") ? Response.json(metadata(JSON.parse(String(init?.body)).ui_revision)) : Response.json({}, { status: 409 })));
 try { rt.mountReadable(name, {}); await rt.mount(options); await assert.rejects(rt.submitReadableCommand(command), /409/); assert.equal(rt.isStopped, false); } finally { rt.disconnect(); }
});
test("trusted BFF only translates current observation and strict input, never client authority", () => {
 const surface = { frontendAppId: "fixture-web", clientSessionId: session, taskId: task, runId: "run-1", metadata: metadata(1) };
 const body = { action: "run", expectedRevision: 2, input: { messages: [], state: { [name]: { route: "/items" } } }, surface: { uiRevision: 1, profileDigest: "c".repeat(64), mountedSnapshotDigest: "e".repeat(64), clientBindingDigest: "1".repeat(64) } };
 const native = nativeReadableCommand(body, surface); assert.equal(native.threadId, task); assert.equal(native.runId, "run-1"); assert.equal(native.input.forwardedProps.clientStateVersion, 1);
 for (const altered of [{ ...body, threadId: session }, { ...body, surface: { ...body.surface, uiRevision: 0 } }, { ...body, input: { ...body.input, forwardedProps: { grant: "stolen" } } }, { ...body, input: { ...body.input, tools: [] } }]) assert.throws(() => nativeReadableCommand(altered, surface));
});
