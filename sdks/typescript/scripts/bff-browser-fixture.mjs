import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";

const prefix = "/api/agent/surfaces/public-binding";
const session = "11111111-1111-4111-8111-111111111111";
const task = "22222222-2222-4222-8222-222222222222";
const effectId = "44444444-4444-4444-8444-444444444444";

export function bffFixtureSource() {
  return `
import { createElement, StrictMode, useState } from "react";
import { z } from "zod";
import { ZebraAgentProvider, useZebraAction, useZebraReadable, useZebraClientStatus } from "@zebra-agent/react";
const config = { mode:"bff" as const, baseUrl:"${prefix}", clientSessionId:"${session}",
 controller:!location.search.includes("observer"), taskId:"${task}",runId:"run-1",runBindingId:"33333333-3333-4333-8333-333333333333",
 clientBindingDigest:"b".repeat(64),actionContractDigests:{"app.ui.item.open":"a".repeat(64)}};
function Panel(){
 const [opened,setOpened]=useState("none");const [count,setCount]=useState(0);
 useZebraReadable("app.ui.route",{route:"/items"});
 useZebraAction("app.ui.item.open",{parameters:z.object({itemId:z.string()}),result:z.object({opened:z.boolean()}),
 handler:({itemId})=>{setOpened(itemId);setCount(n=>n+1);return {opened:true}}});
 return <><output id="bff-status">{useZebraClientStatus()}</output><output id="opened">{opened}</output><output id="executions">{count}</output></>;
}
export function BffFixture(){
 const [mounted,setMounted]=useState(true);
 return <><button id="unmount-bff" onClick={()=>setMounted(false)}>Unmount Agent</button>{mounted&&<StrictMode><ZebraAgentProvider config={config} frontendAppId="fixture-web" profileRevision={1} profileDigest={"c".repeat(64)}><Panel/></ZebraAgentProvider></StrictMode>}</>;
}`;
}

/** Business BFF + native wire emulator, never a production BFF or native proof. */
export function createBffFixture() {
  const login = randomUUID();
  const secrets = { session: randomUUID(), fence: randomUUID(), grant: randomUUID() };
  const state = { origin: "", code: 503, authorized: true, controller: true, pending: false, revision: 0,
    receipts: [], requests: [], nativeCalls: [], mounts: [], releases: 0 };
  const reply = (response, code, body) => { response.writeHead(code, { "content-type": "application/json", "cache-control": "no-store" }); response.end(JSON.stringify(body)); };
  async function handle(request, response) {
    if (request.url === "/fixture/login") {
      response.setHeader("set-cookie", `fixture_business=${login}; HttpOnly; SameSite=Strict; Path=/`);
      reply(response, 200, { loggedIn: true }); return true;
    }
    if (!request.url?.startsWith(prefix + "/")) return false;
    const path = request.url.slice(prefix.length);
    state.requests.push({ path, headers: request.headers });
    if (!state.authorized || request.headers.cookie !== `fixture_business=${login}`) { reply(response, 401, {}); return true; }
    if (request.method === "POST" && request.headers.origin !== state.origin) { reply(response, 403, {}); return true; }
    if (["authorization", "x-zebra-client-session", "x-zebra-client-fence"].some(name => request.headers[name])) { reply(response, 403, {}); return true; }
    const chunks = []; let size = 0;
    for await (const chunk of request) { size += chunk.length; if (size > 65536) { reply(response, 413, {}); return true; } chunks.push(chunk); }
    const raw = Buffer.concat(chunks).toString("utf8");
    let body;
    try { body = raw ? JSON.parse(raw) : {}; } catch { reply(response, 400, {}); return true; }
    if (body === null || typeof body !== "object" || Array.isArray(body)) { reply(response, 400, {}); return true; }
    const sessionPath = `/v1/client-sessions/${session}/`;
    if (!(["mount", "effects", "heartbeat", "release"].some(action => path === sessionPath + action) || path === `/v1/client-effects/${effectId}/receipts`)) { reply(response, 404, {}); return true; }
    if (path.endsWith("/effects") && request.method !== "GET" || !path.endsWith("/effects") && request.method !== "POST") { reply(response, 405, {}); return true; }
    if ((body.task_id && body.task_id !== task) || (body.run_id && body.run_id !== "run-1") || (body.client_session_id && body.client_session_id !== session)) { reply(response, 404, {}); return true; }
    if (path.endsWith("/receipts") && !state.controller) { reply(response, 403, {}); return true; }
    // Server mapping supplies all native credentials; browser fields never choose them.
    state.nativeCalls.push({ path, headers: { Authorization: `Bearer ${secrets.grant}`, "X-Zebra-Client-Session": `${session}:${secrets.session}`, ...(state.controller ? { "X-Zebra-Client-Fence": secrets.fence } : {}) } });
    if (path.endsWith("/mount")) { state.mounts.push(body); state.revision = body.ui_revision; reply(response, 200, {}); }
    else if (path.endsWith("/effects")) {
      const deadline = new Date(Date.now() + 60000).toISOString();
      reply(response, state.code, { effects: state.pending ? [{ effect_id: effectId, task_id: task, run_id: "run-1", surface_instance_id: session,
        action_name: "app.ui.item.open", arguments: { itemId: "item-7" }, status: "pending", expected_ui_revision: state.revision,
        deadline, expires_at: deadline, idempotency_key: "fixture-effect", request_digest: "d".repeat(64),
        action_contract_digest: "a".repeat(64), capability_version: "a".repeat(64), client_binding_digest: "b".repeat(64) }] : [] });
    } else if (path.endsWith("/receipts")) {
      state.receipts.push({ body, key: request.headers["idempotency-key"] });
      state.pending = false;
      // Persist-then-error simulates a lost acceptance response; retry is a receipt replay.
      reply(response, state.receipts.length === 1 ? 500 : 200, { replayed: state.receipts.length > 1 });
    } else { if (path.endsWith("/release")) state.releases++; reply(response, 200, {}); }
    return true;
  }
  return { state, handle };
}

export async function verifyBffBrowser(browser, server, label) {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  const { state } = server.bff;
  try {
    await page.goto(server.url + "/fixture/login");
    await page.goto(server.url + "/index.html?bff=1");
    await page.locator("#bff-status").filter({ hasText: "unavailable" }).waitFor();
    assert.ok(state.mounts.some(mount => mount.mounted_actions.includes("app.ui.item.open") && mount.mounted_readables.includes("app.ui.route")));
    assert.equal(await page.evaluate(() => document.cookie), "");
    state.code = 200; state.pending = true;
    await page.locator("#opened").filter({ hasText: "item-7" }).waitFor();
    await page.locator("#bff-status").filter({ hasText: "ready" }).waitFor();
    assert.equal(await page.locator("#executions").textContent(), "1");
    assert.equal(state.receipts.length, 2);
    assert.equal(state.receipts[0].key, state.receipts[1].key);
    assert.equal(JSON.stringify(state.receipts[0].body), JSON.stringify(state.receipts[1].body));
    const before = state.nativeCalls.length;
    const hostile = await page.evaluate(async ({ prefix, session }) => {
      const response = await fetch(`${prefix}/v1/client-sessions/${session}/heartbeat`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ task_id: "foreign", run_id: "run-1" }) });
      return response.status;
    }, { prefix, session });
    assert.equal(hostile, 404);
    assert.equal(state.nativeCalls.length, before);
    await page.locator("#unmount-bff").click();
    await page.waitForFunction(() => !document.querySelector("#bff-status"));
    await new Promise(resolve => setTimeout(resolve, 100));
    assert.equal(state.releases, 1);
    state.code = 200; state.pending = true; state.controller = false;
    await page.goto(server.url + "/index.html?bff=1&observer=1");
    await page.locator("#bff-status").filter({ hasText: "ready" }).waitFor();
    assert.equal(await page.locator("#executions").textContent(), "0");
    assert.equal(state.receipts.length, 2);
    const nativeBeforeEscalation = state.nativeCalls.length;
    const escalation = await page.evaluate(async ({ prefix, effectId }) => (await fetch(`${prefix}/v1/client-effects/${effectId}/receipts`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ controller: true }) })).status, { prefix, effectId });
    assert.equal(escalation, 403);
    assert.equal(state.nativeCalls.length, nativeBeforeEscalation);
    state.authorized = false;
    await page.locator("#bff-status").filter({ hasText: "stopped" }).waitFor();
    assert.ok(state.requests.every(request => !request.headers.authorization && !request.headers["x-zebra-client-session"] && !request.headers["x-zebra-client-fence"]));
    assert.ok(state.nativeCalls.every(call => Boolean(call.headers.Authorization && call.headers["X-Zebra-Client-Session"])));
    assert.ok(state.nativeCalls.filter(call => call.path.endsWith("/receipts")).every(call => Boolean(call.headers["X-Zebra-Client-Fence"])));
    assert.equal(errors.length, 0);
    console.log(`BFF ${label}: hooks, names-only readable, one action, replayed receipt, observer/rejection, server-only native headers PASS`);
  } finally { await page.close(); }
}
