// QA contract barriers only; fake page/RPC objects are not live acceptance.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";
import { startCommitObserver } from "./browser_commit_observer.mjs";
import { startAuthorityObserver } from "./browser_authority_observer.mjs";
import { startMediaObserver } from "./mediafixtures/browser_media_observer.mjs";
import { startNavigationObserver } from "./browser_navigation_observer.mjs";

const tick = () => new Promise((resolve) => setImmediate(resolve));
function barrier() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}
const runner = new URL("../../../../Trench/toc-frontend/scripts/strategy-joint-acceptance.mjs", import.meta.url);
const sources = [runner, ...["browser_commit_observer.mjs", "browser_navigation_observer.mjs",
  "browser_authority_observer.mjs", "mediafixtures/browser_media_observer.mjs"].map((name) => new URL(name, import.meta.url))];

test("all seventeen fresh guard call sites await; no synchronous native child remains", async () => {
  let count = 0;
  for (const source of sources) {
    const code = await fs.readFile(source, "utf8");
    assert.equal(/\bspawnSync\b/.test(code), false, source.pathname);
    for (const match of code.matchAll(/\bguard\s*\(/g)) {
      if (/function\s+$/.test(code.slice(0, match.index))) continue;
      assert.match(code.slice(0, match.index), /\bawait\s+$/, `${source.pathname}:${match.index}`);
      count += 1;
    }
  }
  assert.equal(count, 17, "call-site inventory must not silently lose a gate");
});

test("commit startup waits for fresh guard before any native clock or poll", async () => {
  const gate = barrier(), calls = [];
  const rpc = { async call(op) { calls.push(op); return op === "clock"
    ? { reading_ms: performance.now(), clock_id: "python" } : { status: "miss" }; }, async close() {} };
  const operation = startCommitObserver({ guard: () => gate.promise, rpc, turn: {}, pollIntervalMs: 10,
    page: { async evaluate() { return { clock_id: "page:1", reading_ms: performance.now(), visibility: "visible" }; } } });
  try { await tick(); assert.deepEqual(calls, []); }
  finally { gate.resolve(); const observer = await operation; await observer.abort(); }
});

test("approval waits both fresh guards before probing and before screenshot", async () => {
  const first = barrier(), second = barrier(), calls = [];
  const turn = { turn_id: "turn", run_id: "run", conversation_key: "conversation" };
  const proof = { status: "ready", ...turn, task_id: "task", event_id: "event", tool_call_id: "call",
    call_fingerprint: "a".repeat(64), message: "Actual pending approval" };
  let guards = 0;
  const observer = startAuthorityObserver({ subcase: "approval", config: { timeout_ms: 5000, evidence_dir: "/qa" },
    guard: () => (++guards === 1 ? first : second).promise,
    probe: async () => { calls.push("probe"); return proof; },
    readSnapshot: async () => ({ status: 200, body: { data: { turn: { ...turn, status: "awaiting_approval" } } } }),
    page: { getByText: () => ({ waitFor: async () => calls.push("visible") }),
      screenshot: async () => calls.push("screenshot") } });
  const operation = observer.beforeOperator(turn);
  try {
    await tick(); assert.deepEqual(calls, []);
    first.resolve(); await tick(); assert.equal(guards, 2); assert.deepEqual(calls, ["probe", "visible"]);
    second.resolve(); await operation; assert.deepEqual(calls, ["probe", "visible", "screenshot", "probe"]);
  } finally { first.resolve(); second.resolve(); await operation.catch(() => {}); }
});

test("media fault cannot abort the browser request before its guard resolves", async () => {
  const gate = barrier(), calls = []; let handler;
  const page = { waitForResponse: () => new Promise(() => {}), on() {},
    route: async (_, callback) => { handler = callback; },
    locator: () => ({ count: async () => 1, getAttribute: async () => "/api/trench-ai/assets/fault" }) };
  await startMediaObserver({ page, caseId: "image", guard: () => gate.promise,
    config: { base_url: "https://localhost", timeout_ms: 5000 } });
  const operation = handler({ request: () => ({ url: () => "https://localhost/api/trench-ai/assets/fault",
    method: () => "GET", resourceType: () => "image" }), abort: async () => calls.push("abort") });
  try { await tick(); assert.deepEqual(calls, []); }
  finally { gate.resolve(); await operation; }
  assert.deepEqual(calls, ["abort"]);
});

test("shared mutation interception holds continue until authorization resolves", async () => {
  const source = await fs.readFile(runner, "utf8");
  const begin = source.indexOf('await page.route("**/*", async (route) => {');
  const end = source.indexOf('\n    });\n    const streams', begin);
  assert.ok(begin > 0 && end > begin);
  const body = source.slice(begin + 'await page.route("**/*", async (route) => {'.length, end);
  const invoke = new (Object.getPrototypeOf(async () => {}).constructor)("route", "guard", "base", "config", "mediaCase",
    `let deniedRequest = false, turnPostCount = 0; ${body}`);
  const gate = barrier(), calls = [];
  const route = { request: () => ({ url: () => "https://localhost/api/trench-ai/conversations/c/turns", method: () => "POST" }),
    continue: async () => calls.push("continue"), abort: async () => calls.push("abort") };
  const operation = invoke(route, () => gate.promise, new URL("https://localhost"), {}, false);
  try { await tick(); assert.deepEqual(calls, []); }
  finally { gate.resolve(); await operation; }
  assert.deepEqual(calls, ["continue"]);
  calls.length = 0;
  await invoke(route, async () => { throw new Error("denied"); }, new URL("https://localhost"), {}, false);
  assert.deepEqual(calls, ["abort"]);
});

test("navigation waits independent guards before each creation and initial goto", async () => {
  const gates = [barrier(), barrier(), barrier()], calls = [], context = {};
  let guarded = 0;
  const page = { context: () => context,
    evaluate: async () => { calls.push("create"); return { conversation_key: `c${calls.length}` }; },
    goto: async () => calls.push("goto"), locator: () => ({ getByText: () => ({ waitFor: async () => {} }) }) };
  const network = { on() {}, send: async () => calls.push("enable") };
  const observer = await startNavigationObserver({ page, context, network, caseId: "navigation",
    config: { base_url: "https://localhost" }, guard: () => gates[guarded++].promise });
  const operation = observer.beforeSubmit();
  try {
    await tick(); assert.deepEqual(calls, []);
    gates[0].resolve(); await tick(); assert.deepEqual(calls, ["create"]);
    gates[1].resolve(); await tick(); assert.deepEqual(calls, ["create", "create"]);
    gates[2].resolve(); await operation; assert.deepEqual(calls, ["create", "create", "goto", "enable"]);
  } finally { for (const gate of gates) gate.resolve(); await operation.catch(() => {}); }
});

test("failure evidence retains exact windows and TLS validation precedes child creation", async () => {
  const source = await fs.readFile(runner, "utf8");
  assert.ok(source.indexOf("assert.match(config.tls_spki") < source.indexOf("openGuardRpc({"));
  const failure = source.slice(source.indexOf("}-failure.json`"), source.indexOf("process.exitCode = 1"));
  assert.match(failure, /mutation_guard_windows: guardWindows/);
  assert.match(failure, /native_observer_windows: nativeWindows/);
});
