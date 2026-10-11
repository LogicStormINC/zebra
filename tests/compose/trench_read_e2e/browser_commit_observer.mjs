// QA-only real visibility polling. No response substitution or product/page state mutation.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { StringDecoder } from "node:string_decoder";
import { fileURLToPath } from "node:url";
import { runNativeCheck } from "./browser_guard_rpc.mjs";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const key = (row) => `${row.event_id}:${row.sequence}`;
const finite = (value) => typeof value === "number" && Number.isFinite(value);
const NON_PUBLICATION = new Set(["meta", "agent_step", "tool_start", "tool_result",
  "thinking", "delta", "answer_reset", "done"]);
function publicationClass(row, paint = false) {
  if (row.type === "public_output") return "publication";
  const authoritative = row.answer_committed === true
    || (paint && Array.isArray(row.markers) && row.markers.includes("final_answer_committed"));
  if (row.type === "answer_reset" && authoritative) return "publication";
  const meaningful = row.meaningful === true || (paint && Array.isArray(row.markers)
    && row.markers.some((marker) => ["first_meaningful_task_communication", "first_meaningful_public_result"].includes(marker)));
  if (NON_PUBLICATION.has(row.type) && !authoritative && !meaningful) return "excluded";
  return "unknown";
}
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const FIELDS = ["eventId", "sequence", "turnId", "outputId", "type", "replay", "applied",
  "backgrounded", "coalesced", "paintSuperseded", "relayReceivedAtMs", "reactCommittedAtMs",
  "paintReadyAtMs", "markers"];
const safePaint = (row) => Object.fromEntries(FIELDS.filter((name) => row[name] !== undefined)
  .map((name) => [name, name === "markers" ? row[name]?.slice(0, 8) : row[name]]));

export async function initializeCommitIdentity({ python, inputsPath, turn, windows, timeoutMs = 15000 }) {
  const output = await runNativeCheck({ python,
    args: [fileURLToPath(new URL("./joint_commit_identity.py", import.meta.url)), "--inputs", inputsPath],
    input: JSON.stringify({ conversation_key: turn.conversation_key, run_id: turn.run_id,
      turn_id: turn.turn_id }) + "\n", timeoutMs, maxBytes: 32768, label: "commit_identity", windows })
    .catch(() => { throw new Error("commit_identity_initialization_failed"); });
  let value;
  try { value = JSON.parse(output); }
  catch { throw new Error("commit_identity_protocol_invalid"); }
  assert.equal(value.conversation_key, turn.conversation_key);
  assert.equal(value.run_id, turn.run_id);
  assert.equal(value.turn_id, turn.turn_id);
  if (value.status === "preparing") return value; // Caller may retry boundedly with the SAME admission.
  assert.equal(value.status, "ready");
  assert.match(value.task_id, UUID);
  assert.match(value.anchor_event_id, UUID);
  assert.ok(Number.isSafeInteger(value.after_sequence) && value.after_sequence >= -1);
  assert.equal(value.floor_basis, "canonical_run_anchor_minus_one");
  assert.equal(value.absence_proof, false);
  return value;
}

export function openCommitProbe({ python, inputsPath, turn, afterSequence }) {
  assert.ok(typeof python === "string" && typeof inputsPath === "string");
  assert.ok(Number.isSafeInteger(afterSequence) && afterSequence >= -1);
  for (const name of ["task_id", "turn_id"]) assert.match(turn[name], UUID);
  assert.ok(typeof turn.run_id === "string" && turn.run_id.length <= 256);
  const child = spawn(python, [fileURLToPath(new URL("./joint_commit_visibility.py", import.meta.url)),
    "--inputs", inputsPath, "--task-id", turn.task_id, "--run-id", turn.run_id,
    "--turn-id", turn.turn_id, "--after-sequence", String(afterSequence)],
  { stdio: ["pipe", "pipe", "ignore"] });
  const decoder = new StringDecoder("utf8");
  let buffer = "", pending = null, closed = false, serial = Promise.resolve(), calls = 0;
  function fail(code) {
    closed = true;
    if (pending) { clearTimeout(pending.timer); pending.reject(new Error(code)); pending = null; }
    child.stdin.destroy();
    if (child.exitCode === null) child.kill();
  }
  child.on("error", () => fail("probe_process_error"));
  child.on("exit", () => fail("probe_process_exit"));
  child.stdin.on("error", () => fail("probe_write_error"));
  child.stdout.on("error", () => fail("probe_read_error"));
  child.stdout.on("data", (chunk) => {
    buffer += decoder.write(chunk);
    if (Buffer.byteLength(buffer) > 1048576) { fail("probe_response_limit"); return; }
    let end;
    while ((end = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, end); buffer = buffer.slice(end + 1);
      try {
        const value = JSON.parse(line);
        assert.ok(pending && value.request_id === pending.id && value.result);
        const current = pending; pending = null; clearTimeout(current.timer);
        current.resolve(value.result);
      } catch { fail("probe_protocol_invalid"); return; }
    }
  });
  return {
    call(op, argumentsValue) {
      const operation = serial.then(() => new Promise((resolve, reject) => {
        if (closed || ++calls > 4096) { reject(new Error("probe_closed_or_call_limit")); return; }
        const id = randomUUID();
        const line = JSON.stringify({ request_id: id, op, arguments: argumentsValue }) + "\n";
        if (Buffer.byteLength(line) > 8192) { reject(new Error("probe_request_limit")); return; }
        pending = { id, resolve, reject,
          timer: setTimeout(() => fail("probe_rpc_deadline"), calls === 1 ? 15000 : 4000) };
        child.stdin.write(line, (error) => { if (error) fail("probe_write_error"); });
      }));
      serial = operation.catch(() => {});
      return operation;
    },
    async close() {
      fail("probe_closed");
      if (child.exitCode !== null) return;
      await new Promise((resolve) => {
        const timer = setTimeout(() => { child.kill("SIGKILL"); resolve(); }, 1000);
        child.once("exit", () => { clearTimeout(timer); resolve(); });
      });
    },
  };
}

export async function calibrateClock(read, referenceClockId, now = () => performance.now()) {
  const send = now();
  const value = await read();
  const returned = now();
  assert.ok(finite(send) && finite(returned) && send <= returned);
  assert.ok(finite(value.reading_ms) && typeof value.clock_id === "string" && value.clock_id);
  if (value.visibility !== undefined) assert.equal(value.visibility, "visible");
  return { reference_clock_id: referenceClockId, remote_clock_id: value.clock_id,
    send_ms: send, remote_ms: value.reading_ms, return_ms: returned, precision_ms: 1 };
}

export async function correlateCommitEvidence({ native, timing, frames, rpc, turn,
  referenceClockId, commitSamples, browserSamples, driftPpm, maxUncertaintyMs = 20,
  requireMeaningful = true, errors = [] }) {
  const results = [], exclusions = [], invalids = [...errors];
  const browserClockId = browserSamples[0]?.remote_clock_id;
  const invalidSnapshot = !Array.isArray(timing?.events) || timing.events.length > 256
    || !finite(timing.timeOriginMs) || browserClockId !== `page:${timing.timeOriginMs}`;
  if (invalidSnapshot) {
    invalids.push("browser_snapshot_clock_or_limit");
  }
  if (!Array.isArray(native?.records) || native.records.length > 256) {
    invalids.push("native_record_limit_or_absent");
    native = { records: [] };
  }
  if (native.invalid_reason) invalids.push(native.invalid_reason);
  const coverage = native.commentary_coverage;
  if (coverage && (coverage.complete !== true || coverage.invalids?.length
    || coverage.missing_output_ids?.length || !Array.isArray(coverage.source_plans)
    || coverage.source_plans.some((source) => source.disposition !== "admitted"))) {
    invalids.push("commentary_coverage_incomplete");
  }
  const targets = new Map();
  for (const frame of frames) {
    const classification = publicationClass(frame);
    if (classification === "excluded") {
      exclusions.push({ event_id: frame.event_id, sequence: frame.sequence, type: frame.type,
        source: "live_frame", status: "excluded", reason: "known_nonpublication_frame" });
      continue;
    }
    if (!UUID.test(frame.event_id) || !Number.isSafeInteger(frame.sequence) || frame.sequence < 0) {
      results.push({ event_id: frame.event_id, sequence: frame.sequence,
        status: "invalid", reason: "noncanonical_live_frame_identity" });
      continue;
    }
    const identity = key(frame);
    if (targets.has(identity)) invalids.push("duplicate_canonical_target_frame");
    targets.set(identity, { ...frame, unknownType: classification === "unknown" });
  }
  const records = new Map();
  for (const record of native.records) {
    const identity = `${record.event_id}:${record.task_sequence}`;
    if (records.has(identity)) invalids.push("duplicate_native_record");
    records.set(identity, record);
    if (!targets.has(identity)) targets.set(identity, { event_id: record.event_id,
      sequence: record.task_sequence, missingFrame: true });
  }
  const paints = Array.isArray(timing?.events) ? timing.events.filter((row) => row.turnId === turn.turn_id) : [];
  for (const paint of paints) {
    const classification = publicationClass(paint, true);
    if (classification === "excluded") {
      exclusions.push({ event_id: paint.eventId, sequence: paint.sequence, type: paint.type,
        source: "browser_timing", status: "excluded", reason: "known_nonpublication_timing" });
      continue;
    }
    if (classification === "unknown") {
      results.push({ event_id: paint.eventId, task_sequence: paint.sequence,
        status: "invalid", reason: "unsupported_publication_paint_type" });
    }
    const identity = `${paint.eventId}:${paint.sequence}`;
    if (!targets.has(identity)) targets.set(identity, { event_id: paint.eventId,
      sequence: paint.sequence, missingFrame: true });
  }
  for (const [identity, frame] of targets) {
    const record = records.get(identity);
    const candidates = paints.filter((row) => row.eventId === frame.event_id && row.sequence === frame.sequence
      && (!record || row.type === (record.event_type === "public_output" ? "public_output" : "answer_reset")));
    let reason;
    if (invalidSnapshot) reason = "browser_snapshot_clock_or_limit";
    else if (frame.unknownType) reason = "unsupported_publication_frame_type";
    else if (frame.missingFrame) reason = "canonical_event_missing_live_frame";
    else if (!record) reason = "live_frame_missing_canonical_visibility";
    else if (record.task_id !== turn.task_id || record.run_id !== turn.run_id || record.turn_id !== turn.turn_id) {
      reason = "native_admission_identity_mismatch";
    } else if (candidates.length !== 1) reason = candidates.length ? "ambiguous_paint_identity" : "canonical_event_missing_paint";
    else if (record.event_type === "answer_committed"
      && !candidates[0].markers?.includes("final_answer_committed")) reason = "authoritative_final_missing_browser_marker";
    if (reason) {
      results.push({ event_id: frame.event_id, task_sequence: frame.sequence, status: "invalid", reason });
      continue;
    }
    try {
      results.push(await rpc.call("interval", { record, paint: safePaint(candidates[0]),
        reference_clock_id: referenceClockId, browser_clock_id: browserClockId,
        browser_samples: browserSamples, commit_samples: commitSamples,
        drift_ppm: driftPpm, max_uncertainty_ms: maxUncertaintyMs }));
    } catch { results.push({ event_id: frame.event_id, task_sequence: frame.sequence,
      status: "invalid", reason: "interval_rpc_failed" }); }
  }
  const meaningfulFrames = frames.filter((row) => row.type === "public_output" && row.meaningful === true);
  if (requireMeaningful && !meaningfulFrames.length) invalids.push("meaningful_milestone_absent");
  if (meaningfulFrames.length && !paints.some((row) => Array.isArray(row.markers)
    && row.markers.includes("first_meaningful_task_communication")
    && meaningfulFrames.some((frame) => frame.event_id === row.eventId && frame.sequence === row.sequence))) {
    invalids.push("meaningful_milestone_missing_browser_marker");
  }
  if (!results.length) invalids.push("no_canonical_paint_targets");
  const count = (status) => results.filter((row) => row.status === status).length;
  return { schema_version: "zebra.browser-commit-visibility.v1", turn_id: turn.turn_id,
    run_id: turn.run_id, reference_clock_id: referenceClockId, results, exclusions, invalids,
    measured: count("measured"), left_censored: count("left_censored"), invalid: count("invalid"),
    total_targets: results.length, require_meaningful_milestone: requireMeaningful,
    complete: !invalids.length && results.length > 0
      && count("measured") === results.length,
    basis: "fresh_read_committed_miss_send_hit_return_to_double_raf_not_physical_presentation",
    calibration: { commit: commitSamples, browser: browserSamples, drift_assumption_ppm: driftPpm,
      max_uncertainty_ms: maxUncertaintyMs },
    native };
}

export async function startCommitObserver({ page, turn, python, inputsPath, afterSequence,
  guard, pollIntervalMs = 25, budgetMs = 60000, driftPpm = 100, maxUncertaintyMs = 20,
  requireMeaningful = true, rpc = null, now = () => performance.now() }) {
  assert.equal(typeof guard, "function");
  assert.ok(Number.isInteger(pollIntervalMs) && pollIntervalMs >= 10 && pollIntervalMs <= 1000);
  assert.ok(finite(budgetMs) && budgetMs > 0 && budgetMs <= 60000);
  assert.ok(finite(driftPpm) && driftPpm >= 0 && driftPpm <= 1000);
  await guard("commit_start");
  const client = rpc ?? openCommitProbe({ python, inputsPath, turn, afterSequence });
  const referenceClockId = `node:${randomUUID()}`, frames = [], errors = [];
  const commitSamples = [], browserSamples = [];
  const started = now();
  let stop = false, finished = false, worker;
  const pageClock = () => page.evaluate(() => ({ clock_id: `page:${performance.timeOrigin}`,
    reading_ms: performance.now(), visibility: document.visibilityState }));
  async function calibration() {
    try { commitSamples.push(await calibrateClock(() => client.call("clock"), referenceClockId, now)); }
    catch { errors.push("native_clock_calibration_failed"); }
    try { browserSamples.push(await calibrateClock(pageClock, referenceClockId, now)); }
    catch { errors.push("browser_clock_calibration_failed"); }
  }
  async function poll() {
    // Exact native namespace/Task/Run reads validate scope; no blocking topology guard here.
    const sent = now();
    const result = await client.call("poll");
    const returned = now();
    if (!finite(sent) || !finite(returned) || returned < sent) throw new Error("node_clock_order");
    if (result.status === "invalid") { errors.push(result.reason ?? "native_poll_invalid"); stop = true; }
    return { status: result.status, reference_send_ms: sent, reference_return_ms: returned };
  }
  try {
    await client.call("clock"); // Startup/preflight is not a calibration RTT sample.
    await pageClock();
    await calibration();
    const initialPoll = await poll(); // A miss here must precede the real target; never fabricate one.
    worker = (async () => {
      while (!stop && now() - started < budgetMs) {
        await delay(pollIntervalMs);
        if (!stop) await poll();
      }
      if (!stop) errors.push("observer_budget_exhausted");
    })().catch(() => { errors.push("native_poll_failed"); stop = true; });
    return {
      initialPoll,
      onFrame(frame) {
        if (finished || frames.length >= 256) { errors.push("observer_frame_limit_or_late_frame"); return; }
        frames.push(Object.fromEntries(["event_id", "sequence", "type", "answer_committed", "meaningful"]
          .filter((name) => frame[name] !== undefined).map((name) => [name, frame[name]])));
      },
      async finish({ timing }) {
        assert.equal(finished, false); finished = true; stop = true;
        try {
          await worker;
          // One final fresh poll covers the terminal before after-calibration and report.
          await poll();
          await calibration();
          const native = await client.call("report");
          await guard("commit_finish"); // Keep the fresh final gate after timing endpoints/calibration.
          return await correlateCommitEvidence({ native, timing, frames, rpc: client, turn,
            referenceClockId, commitSamples, browserSamples, driftPpm, maxUncertaintyMs,
            requireMeaningful, errors });
        } catch {
          return { status: "invalid", reason: "observer_finish_failed", errors,
            total_live_frames: frames.length, complete: false };
        } finally { await client.close(); }
      },
      async abort() { stop = true; await client.close(); await worker; },
    };
  } catch { await client.close(); throw new Error("commit_observer_start_failed"); }
}
