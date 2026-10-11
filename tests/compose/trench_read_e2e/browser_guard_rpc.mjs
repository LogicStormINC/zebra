// Owned QA children only. Private environment/stdin never enter errors or timing records.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { StringDecoder } from "node:string_decoder";
import { fileURLToPath } from "node:url";

const error = (code) => new Error(code);
const validLabel = (label) => typeof label === "string" && /^[a-z_]{1,64}$/.test(label);
const budget = (value) => Number.isFinite(value) && value > 0 && value <= 30000;
function childProcess(python, args, env) {
  const child = spawn(python, args, { env, detached: process.platform !== "win32",
    stdio: ["pipe", "pipe", "ignore"] });
  let finished = false;
  const closed = new Promise((resolve) => child.once("close", (code) => { finished = true; resolve(code); }));
  // Spawn failure still emits close; suppress only the raw OS error/argv.
  child.on("error", () => {});
  return { child, closed, finished: () => finished };
}

async function stopChild(owned) {
  const { child } = owned;
  if (!owned.finished()) {
    // Independent group kill covers Python's Docker/other descendants holding pipes open.
    if (child.pid && process.platform !== "win32") {
      try { process.kill(-child.pid, "SIGKILL"); } catch { /* Independent PID fallback below. */ }
    }
    try { child.kill("SIGKILL"); } catch { /* Still require actual close. */ }
  }
  child.stdin.destroy();
  let timer;
  try {
    await Promise.race([owned.closed, new Promise((_, reject) => {
      timer = setTimeout(() => reject(error("native_child_join_unconfirmed")), 1000);
    })]);
  } finally { clearTimeout(timer); child.stdout.destroy(); }
  // No unref/detach-on-timeout: an unconfirmed child is never reported as cleaned up.
}

export async function closeNativeChild(child, closed, finished) {
  await stopChild({ child, closed, finished });
}

function beginWindow(windows, label, queuedAt = performance.now()) {
  assert.ok(validLabel(label) && Array.isArray(windows) && windows.length < 4096);
  const row = { operation: label, clock: "node.performance.now", time_origin_ms: performance.timeOrigin,
    queued_at_ms: queuedAt, started_at_ms: performance.now(), status: "pending" };
  windows.push(row);
  return row;
}
function endWindow(row, status, closed) {
  row.ended_at_ms = performance.now(); row.duration_ms = row.ended_at_ms - row.queued_at_ms;
  row.status = status; row.child_closed = closed;
}

export async function runNativeCheck({ python, args, input = "", env = process.env, timeoutMs = 7000,
  maxBytes = 65536, label = "native_check", windows = [], signal }) {
  assert.ok(budget(timeoutMs) && Number.isSafeInteger(maxBytes) && maxBytes > 0 && maxBytes <= 1048576);
  assert.ok(typeof input === "string" && Buffer.byteLength(input) <= 32768);
  const window = beginWindow(windows, label), deadline = window.queued_at_ms + timeoutMs;
  const owned = childProcess(python, args, env), { child } = owned;
  const decoder = new StringDecoder("utf8");
  let text = "", bytes = 0, failure, timer;
  let rejectFailure;
  const failed = new Promise((_, reject) => { rejectFailure = reject; });
  const fail = (code) => { if (!failure) { failure = error(code); rejectFailure(failure); } };
  const aborted = () => fail("native_child_cancelled");
  child.on("error", () => fail("native_child_start_failed"));
  child.stdin.on("error", () => fail("native_child_write_failed"));
  child.stdout.on("error", () => fail("native_child_read_failed"));
  child.stdout.on("data", (chunk) => {
    bytes += chunk.byteLength;
    if (bytes > maxBytes) { fail("native_child_output_limit"); return; }
    text += decoder.write(chunk);
  });
  try {
    signal?.addEventListener("abort", aborted, { once: true });
    if (signal?.aborted) aborted();
    timer = setTimeout(() => fail("native_child_deadline"), Math.max(1, deadline - performance.now()));
    if (!failure) child.stdin.end(input);
    const code = await Promise.race([owned.closed, failed]);
    if (failure) throw failure;
    if (signal?.aborted) throw error("native_child_cancelled");
    if (performance.now() >= deadline) throw error("native_child_deadline");
    if (code !== 0) throw error("native_child_failed");
    text += decoder.end();
    await stopChild(owned);
    endWindow(window, "passed", owned.finished());
    return text;
  } catch (primary) {
    try { await stopChild(owned); }
    catch { if (primary instanceof Error) primary.cleanup_unconfirmed = true; }
    endWindow(window, "failed", owned.finished());
    throw primary;
  } finally { clearTimeout(timer); signal?.removeEventListener("abort", aborted); }
}

export function openGuardRpc({ python, env = process.env, windows = [],
  args = [fileURLToPath(new URL("./joint_guard_rpc.py", import.meta.url))] }) {
  const owned = childProcess(python, args, env), { child } = owned;
  const decoder = new StringDecoder("utf8");
  let buffer = "", active, closed = false, failure, stopping, serial = Promise.resolve(), calls = 0;
  const waiting = new Set();
  function fail(code) {
    if (stopping) return stopping;
    closed = true; failure = error(code);
    stopping = stopChild(owned).catch(() => { failure.cleanup_unconfirmed = true; }).then(() => {
      for (const request of waiting) request.reject(failure);
    });
    return stopping;
  }
  child.on("error", () => { void fail("guard_child_start_failed"); });
  child.on("close", () => { if (!closed) void fail("guard_child_closed"); });
  child.stdin.on("error", () => { void fail("guard_child_write_failed"); });
  child.stdout.on("error", () => { void fail("guard_child_read_failed"); });
  child.stdout.on("data", (chunk) => {
    if (closed) return;
    if (Buffer.byteLength(buffer) + chunk.byteLength > 8192) { void fail("guard_response_limit"); return; }
    buffer += decoder.write(chunk);
    let end;
    while ((end = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, end); buffer = buffer.slice(end + 1);
      try {
        // One outstanding request: no next reply is lawful before the next write.
        assert.equal(buffer, "", "trailing guard protocol bytes");
        const value = JSON.parse(line);
        assert.ok(active && Object.keys(value).sort().join() === "request_id,status"
          && value.request_id === active.id && ["passed", "denied"].includes(value.status));
        if (value.status !== "passed") { void fail("guard_denied"); return; }
        const current = active; active = undefined; current.resolve();
      } catch { void fail("guard_protocol_invalid"); return; }
    }
  });
  return {
    pid: child.pid,
    async check(label = "mutation", { timeoutMs = 30000, signal } = {}) {
      assert.ok(validLabel(label) && budget(timeoutMs));
      if (closed) throw failure;
      if (waiting.size >= 32 || ++calls > 4096) {
        await fail("guard_queue_limit"); throw failure;
      }
      const queuedAt = performance.now(), deadline = queuedAt + timeoutMs;
      const window = beginWindow(windows, label, queuedAt);
      window.started_at_ms = null;
      let request, timer;
      const completion = new Promise((resolve, reject) => { request = { id: randomUUID(), resolve, reject }; });
      const aborted = () => { void fail("guard_cancelled"); };
      waiting.add(request);
      signal?.addEventListener("abort", aborted, { once: true });
      if (signal?.aborted) aborted();
      timer = setTimeout(() => { void fail("guard_deadline"); }, timeoutMs);
      const operation = serial.then(async () => {
        if (closed) { await stopping; throw failure; }
        window.started_at_ms = performance.now();
        const remaining = deadline - performance.now();
        if (remaining <= 0) { await fail("guard_deadline"); throw failure; }
        active = request;
        child.stdin.write(JSON.stringify({ request_id: request.id, op: "guard", remaining_ms: remaining }) + "\n",
          (err) => { if (err) void fail("guard_child_write_failed"); });
        await completion;
        if (closed) { await stopping; throw failure; }
        if (signal?.aborted || performance.now() >= deadline) {
          await fail(signal?.aborted ? "guard_cancelled" : "guard_deadline"); throw failure;
        }
      });
      // Attach immediately: queued rejection is never an unhandled promise.
      completion.catch(() => {});
      serial = operation.catch(() => {});
      try { await Promise.race([operation, completion.then(() => operation)]);
        if (closed) { await stopping; throw failure; }
        endWindow(window, "passed", false);
      } catch (primary) {
        if (stopping) await stopping;
        endWindow(window, "failed", owned.finished()); throw primary;
      } finally { clearTimeout(timer); waiting.delete(request); signal?.removeEventListener("abort", aborted); }
    },
    async close() {
      await fail("guard_closed");
      if (!owned.finished()) throw error("native_child_join_unconfirmed");
    },
  };
}
