// QA-only real pending identity plus DOM visibility; never fulfill or inject UI/receipts.
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { runNativeCheck } from "./browser_guard_rpc.mjs";

const SUBCASES = ["cancel", "approval", "scope_denial", "unknown_write_receipt"];
const COUNTERS = ["execution_threads", "model_threads", "public_wait_timers",
  "text_flush_timers", "lease_heartbeat_threads"];

export function startAuthorityObserver({ page, subcase, config, guard, readSnapshot, probe }) {
  assert.ok(SUBCASES.includes(subcase));
  assert.equal(typeof guard, "function");
  assert.ok(config.timeout_ms >= 5000 && config.timeout_ms <= 300000);
  const noFinal = ["cancel", "approval"].includes(subcase);
  let approvalVisibility;
  let admitted;
  let terminalObservedAt;
  const readTurn = async (turn) => {
    const result = await readSnapshot(`/api/trench-ai/turns/${encodeURIComponent(turn.turn_id)}`);
    assert.equal(result.status, 200);
    const current = result.body.data?.turn;
    assert.equal(current?.run_id, turn.run_id);
    assert.equal(current?.conversation_key, turn.conversation_key);
    return current;
  };
  const nativeProbe = probe ?? (async (turn, remaining) => {
    const script = fileURLToPath(new URL("./joint_authority_observation.py", import.meta.url));
    const output = await runNativeCheck({ python: config.python, args: [script],
      input: JSON.stringify(turn), maxBytes: 65536, windows: config.native_windows,
      label: "approval_identity", timeoutMs: Math.min(5000, Math.max(1, remaining)) });
    return JSON.parse(output);
  });
  function exactPending(proof, turn) {
    assert.equal(proof.status, "ready");
    for (const key of ["run_id", "conversation_key", "turn_id"]) assert.equal(proof[key], turn[key]);
    assert.match(proof.call_fingerprint, /^[a-f0-9]{64}$/);
    assert.ok(typeof proof.tool_call_id === "string" && proof.tool_call_id.length > 0);
    assert.ok(typeof proof.message === "string" && proof.message.length > 0 && proof.message.length <= 8192);
    assert.ok(proof.event_id && proof.task_id);
  }
  async function beforeOperator(turn) {
    admitted = { conversation_key: turn.conversation_key, run_id: turn.run_id, turn_id: turn.turn_id };
    const payload = { case_id: "authority", subcase, ...admitted };
    if (subcase === "unknown_write_receipt") {
      assert.match(config.source_id ?? "", /^[a-f0-9]{32}$/);
      payload.source_id = config.source_id;
    }
    if (subcase !== "approval") return payload;
    await guard("approval_before_probe");
    const deadline = performance.now() + config.timeout_ms;
    let proof;
    for (let polls = 0; polls < 256 && performance.now() < deadline; polls += 1) {
      proof = await nativeProbe(admitted, deadline - performance.now());
      if (proof.status !== "preparing") break;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    exactPending(proof, admitted);
    assert.equal((await readTurn(admitted)).status, "awaiting_approval");
    await page.getByText(proof.message, { exact: true }).waitFor({
      state: "visible", timeout: Math.max(1, deadline - performance.now()),
    }); // Strict locator: duplicated or absent approval text cannot count as displayed.
    await guard("approval_before_screenshot");
    const screenshot = path.join(config.evidence_dir, "approval-before-decision.png");
    await page.screenshot({ path: screenshot, fullPage: true });
    const stillPending = await nativeProbe(admitted, deadline - performance.now());
    exactPending(stillPending, admitted);
    for (const key of ["event_id", "tool_call_id", "call_fingerprint", "message", "task_id"]) {
      assert.equal(stillPending[key], proof[key], "approval changed during DOM observation");
    }
    approvalVisibility = { tool_call_id: proof.tool_call_id, call_fingerprint: proof.call_fingerprint,
      event_id: proof.event_id, before_decision: true, screenshot };
    return payload;
  }
  function onFrame(frame, event) {
    if (typeof event.status === "string") frame.status = event.status;
  }
  function acceptsStreamEnd(frames) {
    if (!noFinal || frames.some((f) => f.answer_committed === true)) return false;
    return frames.some((f) => ["cancelled", "error"].includes(f.type)
      || subcase === "approval" && approvalVisibility && f.type === "done"
      && ["awaiting_approval", "waiting_approval", "waiting_input"].includes(f.status));
  }
  async function waitTerminal(turn) {
    assert.equal(noFinal, true);
    const deadline = performance.now() + config.timeout_ms;
    while (performance.now() < deadline) {
      const current = await readTurn(turn);
      if (current.status === (subcase === "cancel" ? "cancelled" : "failed")) {
        terminalObservedAt = performance.now();
        return current;
      }
      assert.ok(!["completed", "partial", "blocked", "failed", "cancelled"].includes(current.status),
        "authority stopped in an unexpected terminal state");
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    assert.fail("actual non-answer terminal was not observed");
  }
  function terminalCleanup(operator) {
    assert.equal(noFinal, true);
    assert.ok(Number.isFinite(terminalObservedAt));
    assert.equal(operator.subcase, subcase);
    const native = operator.native;
    assert.equal(native.run_id, admitted.run_id);
    assert.equal(native.status, subcase === "cancel" ? "cancelled" : "failed");
    assert.equal(native.lease.released, true);
    assert.equal(native.worker.coverage_complete, true);
    for (const key of COUNTERS) assert.equal(native.worker[key], 0);
    assert.equal(native.rows.filter((r) => r.event_type === "answer_committed").length, 0);
    const elapsed = performance.now() - terminalObservedAt;
    assert.ok(elapsed <= 5000, "native authority cleanup must remain bounded");
    return { status: "passed", native, terminal_observed_to_cleanup_ms: elapsed };
  }
  return { noFinal, beforeOperator, onFrame, acceptsStreamEnd, waitTerminal, terminalCleanup,
    evidence: () => ({ authority_subcase: subcase, healthy_samples: 0,
      ...(approvalVisibility ? { approval_visibility: approvalVisibility } : {}) }) };
}
