// Contract checks with explicitly mocked I/O, never real browser/operator acceptance.
import assert from "node:assert/strict";
import test from "node:test";
import { startAuthorityObserver } from "./browser_authority_observer.mjs";

function setup(subcase, overrides = {}) {
  const calls = [];
  const turn = { turn_id: "turn", run_id: "run", conversation_key: "conversation" };
  const proof = { status: "ready", ...turn, tool_call_id: "call", call_fingerprint: "a".repeat(64),
    event_id: "event", message: "Actual approval message", task_id: "task" };
  const page = { getByText(message, options) { calls.push(["dom", message, options]);
    return { waitFor: async () => calls.push("visible") }; },
  screenshot: async () => calls.push("screenshot") };
  const options = { page, subcase, config: { timeout_ms: 5000, evidence_dir: "/qa" },
    guard: () => calls.push("guard"), probe: async () => proof,
    readSnapshot: async () => ({ status: 200, body: { data: { turn: { ...turn, status: "awaiting_approval" } } } }),
    ...overrides };
  return { observer: startAuthorityObserver(options), calls, turn, proof };
}

test("approval operator starts only after canonical waiting approval and actual DOM screenshot", async () => {
  const { observer, calls, turn, proof } = setup("approval");
  const payload = await observer.beforeOperator(turn);
  assert.deepEqual(payload, { case_id: "authority", subcase: "approval", ...turn });
  assert.deepEqual(calls, ["guard", ["dom", proof.message, { exact: true }], "visible", "guard", "screenshot"]);
  assert.deepEqual(observer.evidence().approval_visibility, {
    tool_call_id: "call", call_fingerprint: "a".repeat(64), event_id: "event",
    before_decision: true, screenshot: "/qa/approval-before-decision.png",
  });
});

for (const defect of ["run", "conversation", "fingerprint", "status", "terminal", "message", "duplicate_dom"]) {
  test(`mismatched or undisplayed approval cannot dispatch operator: ${defect}`, async () => {
    const { observer, turn, proof, calls } = setup("approval", defect === "status" ? {
      readSnapshot: async () => ({ status: 200, body: { data: { turn: { run_id: "other" } } } }),
    } : defect === "duplicate_dom" ? {
      page: { getByText: () => ({ waitFor: async () => { throw new Error("not exact visible DOM"); } }),
        screenshot: async () => assert.fail("no screenshot") },
    } : {});
    if (defect === "run") proof.run_id = "other";
    if (defect === "conversation") proof.conversation_key = "other";
    if (defect === "fingerprint") proof.call_fingerprint = "invented";
    if (defect === "terminal") proof.status = "terminal";
    if (defect === "message") proof.message = "";
    await assert.rejects(observer.beforeOperator(turn));
    assert.equal(calls.includes("screenshot"), false);
  });
}

test("cancel requires no fake final or approval and includes exact native target fields", async () => {
  const { observer, turn } = setup("cancel", { probe: () => assert.fail("not an approval") });
  assert.deepEqual(await observer.beforeOperator(turn), { case_id: "authority", subcase: "cancel", ...turn });
  assert.equal(observer.noFinal, true);
  assert.equal(observer.acceptsStreamEnd([{ type: "done" }]), false);
  assert.equal(observer.acceptsStreamEnd([{ type: "error" }]), true);
  assert.equal(observer.acceptsStreamEnd([{ type: "cancelled", answer_committed: true }]), false);
});

test("approval interrupt may end its own stream only after real pending DOM was observed", async () => {
  const { observer, turn } = setup("approval");
  const frame = { type: "done", status: "awaiting_approval" };
  assert.equal(observer.acceptsStreamEnd([frame]), false);
  await observer.beforeOperator(turn);
  assert.equal(observer.acceptsStreamEnd([frame]), true);
});

for (const subcase of ["scope_denial", "unknown_write_receipt"]) {
  test(`${subcase} retains the normal unique final gate and targets only the seeded source`, async () => {
    const { observer, turn } = setup(subcase);
    assert.equal(observer.noFinal, false);
    assert.equal(observer.acceptsStreamEnd([{ type: "done" }]), false);
    if (subcase === "unknown_write_receipt") {
      await assert.rejects(observer.beforeOperator(turn));
      const target = setup(subcase, { config: { timeout_ms: 5000, evidence_dir: "/qa", source_id: "a".repeat(32) } });
      assert.equal((await target.observer.beforeOperator(turn)).source_id, "a".repeat(32));
    } else assert.equal((await observer.beforeOperator(turn)).run_id, turn.run_id);
  });
}

test("pending identity changed during screenshot cannot dispatch a decision", async () => {
  let probes = 0;
  const { observer, turn } = setup("approval", { probe: async (admitted) => ({
    status: "ready", ...admitted, task_id: "task", message: "Approval is pending",
    tool_call_id: "call", event_id: ++probes === 1 ? "first" : "changed",
    call_fingerprint: "a".repeat(64),
  }) });
  await assert.rejects(observer.beforeOperator(turn), /approval changed/);
  assert.equal(observer.evidence().approval_visibility, undefined);
});

test("actual terminal and zero native counters are required; normal completion is rejected", async () => {
  const { observer, turn } = setup("cancel", { readSnapshot: async () => ({
    status: 200, body: { data: { turn: { turn_id: "turn", run_id: "run",
      conversation_key: "conversation", status: "cancelled" } } },
  }) });
  await observer.beforeOperator(turn);
  assert.throws(() => observer.terminalCleanup({}), /assertion/i);
  await observer.waitTerminal(turn);
  const native = { run_id: "run", status: "cancelled", lease: { released: true }, rows: [],
    worker: { coverage_complete: true, execution_threads: 0, model_threads: 0,
      public_wait_timers: 0, text_flush_timers: 0, lease_heartbeat_threads: 0 } };
  assert.equal(observer.terminalCleanup({ subcase: "cancel", native }).status, "passed");
  native.worker.model_threads = 1;
  assert.throws(() => observer.terminalCleanup({ subcase: "cancel", native }));
  native.worker.model_threads = 0;
  native.rows.push({ event_type: "answer_committed" });
  assert.throws(() => observer.terminalCleanup({ subcase: "cancel", native }));
  const other = setup("cancel", { readSnapshot: async () => ({ status: 200,
    body: { data: { turn: { run_id: "run", conversation_key: "conversation", status: "completed" } } } }) });
  await assert.rejects(other.observer.waitTerminal(turn), /unexpected terminal/);
});
