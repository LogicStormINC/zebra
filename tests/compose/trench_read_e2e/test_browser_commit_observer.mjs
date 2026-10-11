// Contract guards only: mock RPC receipts are NOT live provider/browser acceptance.
import assert from "node:assert/strict";
import test from "node:test";
import { randomUUID } from "node:crypto";
import { calibrateClock, correlateCommitEvidence, initializeCommitIdentity, startCommitObserver } from "./browser_commit_observer.mjs";

function evidence() {
  const turn = { task_id: randomUUID(), run_id: randomUUID(), turn_id: randomUUID() };
  const id = randomUUID(), calls = [];
  return {
    turn, calls, referenceClockId: "node", driftPpm: 100,
    commitSamples: [{ remote_clock_id: "python" }], browserSamples: [{ remote_clock_id: "page:123" }],
    native: { records: [{ event_id: id, task_sequence: 21, event_type: "public_output",
      task_id: turn.task_id, turn_id: turn.turn_id, run_id: turn.run_id, output_id: "out:1",
      status: "measured", clock_id: "python", commit_interval_ms: [10, 15] }] },
    frames: [{ event_id: id, sequence: 21, cursor: 9, type: "public_output", meaningful: true }],
    timing: { timeOriginMs: 123, events: [{ eventId: id, sequence: 21, relaySequence: 9,
      turnId: turn.turn_id, outputId: "out:1", type: "public_output", replay: false, applied: true,
      backgrounded: false, relayReceivedAtMs: 20, reactCommittedAtMs: 22, paintReadyAtMs: 24,
      markers: ["first_meaningful_task_communication"], PRIVATE_BODY: "SECRET" }] },
    rpc: { async call(op, argumentsValue) {
      calls.push({ op, argumentsValue });
      return { event_id: argumentsValue.record.event_id, status: argumentsValue.record.status,
        interval_ms: argumentsValue.record.status === "measured" ? [5, 14] : null };
    } },
  };
}

test("initializer failure cannot synthesize Task identity or expose private inputs", async () => {
  const input = evidence();
  await assert.rejects(initializeCommitIdentity({ python: "/bin/false",
    inputsPath: "/private/SECRET-inputs", turn: { ...input.turn, conversation_key: "c" } }),
  /^Error: commit_identity_initialization_failed$/);
});

test("canonical UUID and Task sequence join, never relay cursor; no bodies leave page timing", async () => {
  const input = evidence();
  const result = await correlateCommitEvidence(input);
  assert.equal(result.complete, true);
  assert.equal(result.measured, 1);
  assert.equal(input.calls[0].op, "interval");
  assert.equal(input.calls[0].argumentsValue.paint.sequence, 21);
  assert.ok(!JSON.stringify(input.calls).includes("SECRET"));
  input.timing.events[0].sequence = 9;
  assert.equal((await correlateCommitEvidence(input)).complete, false);
});

for (const change of ["frame", "paint", "native", "namespace-admission", "clock", "marker", "duplicate"]) {
  test(`missing or ambiguous ${change} is retained, not a pass`, async () => {
    const input = evidence();
    if (change === "frame") input.frames = [];
    if (change === "paint") input.timing.events = [];
    if (change === "native") input.native.records = [];
    if (change === "namespace-admission") input.native.records[0].task_id = randomUUID();
    if (change === "clock") input.timing.timeOriginMs = 124;
    if (change === "marker") input.timing.events[0].markers = [];
    if (change === "duplicate") input.timing.events.push({ ...input.timing.events[0] });
    const result = await correlateCommitEvidence(input);
    assert.equal(result.complete, false);
    assert.ok(result.total_targets > 0);
    assert.ok(result.invalid > 0 || result.invalids.length > 0);
  });
}

test("known nonpublication capture types excluded explicitly; unknown publication fails closed", async () => {
  const input = evidence(), id = randomUUID();
  input.frames.push({ type: "meta", event_id: id, sequence: 3, meaningful: false });
  input.timing.events.push({ type: "meta", eventId: id, sequence: 3, turnId: input.turn.turn_id });
  let result = await correlateCommitEvidence(input);
  assert.equal(result.complete, true);
  assert.equal(result.exclusions.length, 2);
  for (const type of ["agent_step", "tool_start", "tool_result", "thinking", "delta", "done"]) {
    const event_id = randomUUID();
    input.frames.push({ type, event_id, sequence: 18 });
    input.timing.events.push({ type, eventId: event_id, sequence: 18, turnId: input.turn.turn_id });
  }
  result = await correlateCommitEvidence(input);
  assert.equal(result.complete, true);
  assert.equal(result.total_targets, 1);
  assert.equal(result.exclusions.length, 14);
  input.frames.push({ type: "public_update", event_id: randomUUID(), sequence: 19 });
  result = await correlateCommitEvidence(input);
  assert.equal(result.complete, false);
  assert.equal(result.total_targets, 2);
  input.frames[0].meaningful = false;
  assert.ok((await correlateCommitEvidence(input)).invalids.includes("meaningful_milestone_absent"));
});

test("actual authoritative answer_reset capture measures canonical final, not terminal done", async () => {
  const input = evidence(), event_id = randomUUID();
  input.native.records.push({ ...input.native.records[0], event_id, task_sequence: 23,
    event_type: "answer_committed", output_id: undefined });
  input.frames.push({ type: "answer_reset", answer_committed: true, event_id, sequence: 23 });
  input.timing.events.push({ ...input.timing.events[0], eventId: event_id, sequence: 23,
    type: "answer_reset", markers: ["final_answer_committed"] });
  input.frames.push({ type: "done", event_id: randomUUID(), sequence: 24 });
  const result = await correlateCommitEvidence(input);
  assert.equal(result.complete, true);
  assert.equal(result.measured, 2);
  assert.equal(result.exclusions.at(-1).type, "done");
  input.frames[1].answer_committed = false;
  assert.equal((await correlateCommitEvidence(input)).complete, false);
});

for (const type of ["public_update", "unknown", "error"]) {
  test(`${type} never silently excluded`, async () => {
    const input = evidence();
    input.frames.push({ type, event_id: randomUUID(), sequence: 30 });
    assert.equal((await correlateCommitEvidence(input)).complete, false);
  });
}

test("captured tool-loop meta/public_update pair stays fail-closed on both frame and paint", async () => {
  const input = evidence();
  // v4 native MODEL_RESPONSE_RECEIVED tool_loop, not PUBLIC_OUTPUT or ANSWER_COMMITTED.
  const id = "3a051bf3-bedb-410a-adcb-5279d66780d0";
  for (const [type, cursor] of [["meta", 5], ["public_update", 6]]) {
    input.frames.push({ event_id: id, sequence: 10, type, cursor });
    input.timing.events.push({ eventId: id, sequence: 10, relaySequence: cursor,
      turnId: input.turn.turn_id, type, replay: false, applied: true, backgrounded: false,
      relayReceivedAtMs: 20, reactCommittedAtMs: 22, markers: [],
      ...(type === "meta" ? { paintSuperseded: true } : { paintReadyAtMs: 24 }) });
  }
  const result = await correlateCommitEvidence(input);
  assert.equal(result.complete, false);
  assert.equal(result.measured, 1);
  assert.equal(result.invalid, 2);
  assert.deepEqual(result.results.filter((row) => row.event_id === id).map((row) => row.reason),
    ["unsupported_publication_paint_type", "unsupported_publication_frame_type"]);
  assert.equal(result.exclusions.filter((row) => row.event_id === id).length, 2);
  assert.ok(result.exclusions.filter((row) => row.event_id === id).every((row) => row.type === "meta"));
  assert.equal(input.calls.length, 1); // No invented native COMMIT interval for public_update.
});

for (const disposition of ["quota_exhausted", "text_limit", "admitted"]) {
  test(`canonical source ${disposition} gap cannot vanish behind Host meta exclusion`, async () => {
    const input = evidence();
    input.native.commentary_coverage = { complete: disposition !== "admitted", invalids: [],
      source_plans: [{ disposition, output_ids: ["planned-but-missing"] }],
      missing_output_ids: disposition === "admitted" ? ["planned-but-missing"] : [] };
    const result = await correlateCommitEvidence(input);
    assert.equal(result.complete, false);
    assert.ok(result.invalids.includes("commentary_coverage_incomplete"));
  });
}

test("left-censored retained and process interval failure cannot silently omit a row", async () => {
  const input = evidence();
  input.native.records[0].status = "left_censored";
  let result = await correlateCommitEvidence(input);
  assert.equal(result.left_censored, 1);
  assert.equal(result.complete, false);
  input.rpc.call = async () => { throw new Error("password=SECRET"); };
  result = await correlateCommitEvidence(input);
  assert.equal(result.invalid, 1);
  assert.ok(!JSON.stringify(result).includes("SECRET"));
});

test("calibration brackets asynchronous remote reads and rejects hidden page", async () => {
  const ticks = [10, 14];
  assert.deepEqual(await calibrateClock(async () => ({ reading_ms: 3, clock_id: "remote" }),
    "node", () => ticks.shift()), { reference_clock_id: "node", remote_clock_id: "remote",
    send_ms: 10, remote_ms: 3, return_ms: 14, precision_ms: 1 });
  await assert.rejects(calibrateClock(async () => ({ reading_ms: 3, clock_id: "remote", visibility: "hidden" }), "node"));
});

test("persistent polling starts with paired calibration/miss and finish closes owned RPC", async () => {
  const input = evidence(), calls = [];
  let closed = false, guards = 0;
  const rpc = { async call(op, args) {
    calls.push(op);
    if (op === "clock") return { reading_ms: performance.now(), clock_id: "python" };
    if (op === "poll") return { status: "miss" };
    if (op === "report") return input.native;
    return input.rpc.call(op, args);
  }, async close() { closed = true; } };
  const page = { async evaluate() { return { reading_ms: performance.now(), clock_id: "page:123", visibility: "visible" }; } };
  const observer = await startCommitObserver({ page, rpc, turn: input.turn,
    guard() { guards += 1; }, pollIntervalMs: 10 });
  assert.deepEqual(calls.slice(0, 3), ["clock", "clock", "poll"]);
  assert.equal(observer.initialPoll.status, "miss");
  observer.onFrame(input.frames[0]);
  await new Promise((resolve) => setTimeout(resolve, 25));
  assert.equal(guards, 1, "background polls must not synchronously re-run topology preflight");
  const result = await observer.finish({ timing: input.timing });
  assert.equal(result.complete, true);
  assert.equal(closed, true);
  assert.ok(calls.filter((op) => op === "poll").length >= 3);
  assert.equal(guards, 2, "one start and one finish guard, regardless of poll count");
  assert.equal(result.calibration.commit.length, 2);
  assert.equal(result.calibration.browser.length, 2);
  await assert.rejects(observer.finish({ timing: input.timing }));
});
