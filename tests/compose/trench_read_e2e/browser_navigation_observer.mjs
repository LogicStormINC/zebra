// Genuine same-scratch browser faults. No response fulfillment, provider stub or DOM injection.
import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createCapture } from "./joint_sse.mjs";
import { runNativeCheck } from "./browser_guard_rpc.mjs";

export async function startNavigationObserver({ page, context, network, caseId, config, guard }) {
  assert.ok(["frame_disconnect", "navigation"].includes(caseId));
  assert.equal(typeof guard, "function");
  assert.equal(page.context(), context);
  const base = new URL(config.base_url).origin;
  const result = { scope: "actual_browser_observation_faults", fixture_provider: false,
    fault_cohort: true, healthy_samples: 0, observe_only: false };
  const requests = [];
  const streams = new Set();
  const finished = new Set();
  const injectedFailures = new Set();
  let seed;
  let ackTurn;
  let ackTask;
  let faultTask;
  let faultAt = null;
  let transportFailed = false;
  let reconnected = false;
  let observerError = false;
  let faultWindow = false;
  let firstFrameResolve;
  const firstFrame = new Promise((resolve) => { firstFrameResolve = resolve; });
  const requestListener = ({ requestId, request }) => {
    const url = new URL(request.url);
    if (url.origin !== base || !url.pathname.startsWith("/api/trench-ai/")) return;
    if (requests.length >= 2048) { observerError = true; return; }
    requests.push({ path: url.pathname, method: request.method, at: performance.now() });
    if (/\/turns\/[^/]+\/events$/.test(url.pathname)
      && url.searchParams.get("qa_navigation_probe") !== "1") streams.add(requestId);
  };
  const failedListener = ({ requestId }) => {
    if (faultWindow && streams.has(requestId)) {
      injectedFailures.add(requestId);
      if (faultAt !== null) transportFailed = true;
    }
  };
  const responseListener = ({ response }) => {
    const url = new URL(response.url);
    if (faultAt !== null && performance.now() > faultAt && response.status === 200
      && url.searchParams.get("qa_navigation_probe") !== "1"
      && url.origin === base && (/\/turns\/[^/]+\/events$/.test(url.pathname)
        || /\/conversations\/[^/]+\/snapshot$/.test(url.pathname))) reconnected = true;
  };
  network.on("Network.requestWillBeSent", requestListener);
  network.on("Network.loadingFailed", failedListener);
  network.on("Network.responseReceived", responseListener);
  const finishedListener = ({ requestId }) => { if (finished.size < 2048) finished.add(requestId); };
  network.on("Network.loadingFinished", finishedListener);
  async function spa(key, label) {
    const epoch = await page.evaluate(() => performance.timeOrigin);
    await guard("navigation_spa");
    faultWindow = true;
    await page.locator("aside").getByText(label, { exact: true }).click();
    await page.waitForURL((url) => url.pathname === `/dashboard/strategy/${key}`);
    faultWindow = false;
    assert.equal(await page.evaluate(() => performance.timeOrigin), epoch, "SPA switch required");
  }
  const pausedListener = (event) => {
    if (!event.responseStatusCode) return;
    const url = new URL(event.request.url);
    if (url.origin !== base || event.request.method !== "POST"
      || !/\/conversations\/[^/]+\/turns$/.test(url.pathname)) {
      void network.send("Fetch.continueResponse", { requestId: event.requestId });
      return;
    }
    ackTask = (async () => {
      assert.ok(seed && !ackTurn, "only one real admission may be delayed");
      assert.equal(event.responseStatusCode, 202);
      const response = await network.send("Fetch.getResponseBody", { requestId: event.requestId });
      const bytes = response.base64Encoded ? Buffer.from(response.body, "base64") : Buffer.from(response.body);
      assert.ok(bytes.byteLength <= 32768);
      const envelope = JSON.parse(bytes.toString());
      assert.equal(envelope.success, true);
      ackTurn = envelope.data.turn;
      assert.equal(ackTurn.conversation_key, seed.a_key);
      assert.ok(!["completed", "failed", "cancelled"].includes(ackTurn.status));
      await spa(seed.b_key, seed.b_label);
      const settled = finished.has(event.networkId) ? Promise.resolve() : new Promise((resolve, reject) => {
        const timer = setTimeout(() => { network.off("Network.loadingFinished", done);
          reject(new Error("late response never completed")); }, 5000);
        const done = ({ requestId }) => {
          if (requestId === event.networkId) {
            clearTimeout(timer); network.off("Network.loadingFinished", done); resolve();
          }
        };
        network.on("Network.loadingFinished", done);
      });
      settled.catch(() => {});
      await guard("navigation_ack_release");
      // Continue the ORIGINAL response. No fulfill, body substitution or fabricated ACK.
      await network.send("Fetch.continueResponse", { requestId: event.requestId });
      await settled;
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      assert.equal(new URL(page.url()).pathname, `/dashboard/strategy/${seed.b_key}`);
      assert.equal(await page.locator("[data-message-id]").filter({ hasText: config.expected }).count(), 0);
      result.navigation = { ...seed, late_ack: true, b_not_contaminated: true,
        response_unmodified: true, spa_navigation: true,
        admission_sha256: createHash("sha256").update(bytes).digest("hex") };
    })().catch(() => { observerError = true; });
  };
  async function beforeSubmit() {
    if (caseId !== "navigation") return;
    const suffix = randomUUID().slice(0, 8);
    const labels = [`QA navigation A ${suffix}`, `QA navigation B ${suffix}`];
    const conversations = [];
    for (const label of labels) {
      await guard("navigation_create");
      const conversation = await page.evaluate(async (title) => {
        const response = await fetch("/api/trench-ai/conversations", { method: "POST",
          credentials: "include", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ label: title, bias: "", market: "" }) });
        if (!response.ok) throw new Error("scratch conversation creation failed");
        const body = await response.json();
        if (body.success !== true) throw new Error("business admission rejected");
        return body.data.conversation;
      }, label);
      assert.ok(conversation.conversation_key);
      conversations.push(conversation.conversation_key);
    }
    seed = { a_key: conversations[0], b_key: conversations[1], a_label: labels[0], b_label: labels[1] };
    assert.notEqual(seed.a_key, seed.b_key);
    await guard("navigation_goto");
    await page.goto(`/dashboard/strategy/${seed.a_key}`, { waitUntil: "domcontentloaded" });
    await page.locator("aside").getByText(seed.b_label, { exact: true }).waitFor();
    network.on("Fetch.requestPaused", pausedListener);
    await network.send("Fetch.enable", { patterns: [{ urlPattern: `${base}/api/trench-ai/conversations/*/turns`,
      requestStage: "Response" }] });
  }
  async function active(turn) {
    return page.evaluate(async (id) => {
      const response = await fetch(`/api/trench-ai/turns/${encodeURIComponent(id)}`,
        { credentials: "include", cache: "no-store" });
      if (!response.ok) return false;
      return ["accepted", "queued", "dispatching", "running"].includes((await response.json()).data?.turn?.status);
    }, turn.turn_id);
  }
  async function afterAdmission(turn) {
    if (caseId !== "navigation") return;
    assert.ok(ackTask);
    await ackTask;
    assert.equal(observerError, false, "late ACK fault failed");
    assert.equal(turn.turn_id, ackTurn.turn_id);
    assert.equal(turn.run_id, ackTurn.run_id);
    await spa(seed.a_key, seed.a_label);
    let timer;
    try {
      await Promise.race([firstFrame, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("no live frame")), 10000);
      })]);
    } finally { clearTimeout(timer); }
    assert.ok(await active(turn), "refresh must interrupt a real active observation");
    await guard("navigation_reload");
    faultWindow = true;
    await page.reload({ waitUntil: "domcontentloaded" });
    faultWindow = false;
    await page.getByRole("textbox").waitFor();
    await spa(seed.b_key, seed.b_label);
    assert.equal(await page.locator("[data-message-id]").filter({ hasText: config.expected }).count(), 0);
    await spa(seed.a_key, seed.a_label);
    result.navigation = { ...result.navigation, refresh: true, a_b_a: true, same_admission: true };
  }
  function onFrame(frame, event) {
    if (event.answer_committed === true || ["done", "error"].includes(event.type)) return;
    firstFrameResolve();
    if (caseId !== "frame_disconnect" || faultTask) return;
    faultTask = (async () => {
      faultAt = performance.now();
      await guard("navigation_offline");
      faultWindow = true;
      await network.send("Network.emulateNetworkConditions", { offline: true, latency: 0,
        downloadThroughput: 0, uploadThroughput: 0 });
      // Real UI request transport failure, not just a synthetic online/offline DOM event.
      for (let i = 0; i < 100 && !transportFailed; i += 1) {
        await new Promise((resolve) => setTimeout(resolve, 20));
      }
      await guard("navigation_online");
      await network.send("Network.emulateNetworkConditions", { offline: false, latency: 0,
        downloadThroughput: -1, uploadThroughput: -1 });
      faultWindow = false;
      assert.ok(transportFailed, "the real in-flight UI stream was not disconnected");
    })().catch(() => { observerError = true; });
  }
  async function readBrowser(turnId, cursor, cut) {
    // Actual Chromium fetch + reader cancellation on the first full SSE frame.
    // Node createCapture remains the authoritative parser, and no raw body is persisted.
    const read = await page.evaluate(async ({ id, after, stop, timeout }) => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeout);
      const decoder = new TextDecoder();
      let bytes = 0, pending = "", body = "", aborted = false, cancelled = false;
      try {
        const response = await fetch(`/api/trench-ai/turns/${encodeURIComponent(id)}/events?cursor=${after}&qa_navigation_probe=1`,
          { credentials: "include", headers: { Accept: "text/event-stream", "Last-Event-ID": String(after) },
            signal: controller.signal });
        if (!response.ok || !response.body || !response.headers.get("content-type")?.includes("text/event-stream")) {
          throw new Error("real replay response invalid");
        }
        const reader = response.body.getReader();
        while (true) {
          const chunk = await reader.read();
          if (chunk.done) {
            body += pending + decoder.decode();
            return { body, eof: true, request_started: true };
          }
          bytes += chunk.value.byteLength;
          if (bytes > 1048576) throw new Error("replay byte limit");
          pending += decoder.decode(chunk.value, { stream: true });
          if (stop) {
            let boundary;
            while ((boundary = pending.match(/\r?\n\r?\n/))) {
              const block = pending.slice(0, boundary.index + boundary[0].length);
              pending = pending.slice(block.length);
              if (!/^data:/m.test(block)) continue;
              if (!/^id:\s*\d+/m.test(block)) throw new Error("unpositioned observation problem");
              body = block;
              await reader.cancel(); cancelled = true;
              controller.abort(); aborted = controller.signal.aborted;
              return { body, eof: false, request_started: true, reader_cancelled: cancelled, abort_called: aborted };
            }
          }
          if (!stop) { body += pending; pending = ""; }
        }
      } finally { clearTimeout(timer); }
    }, { id: turnId, after: cursor, stop: cut, timeout: Math.min(config.timeout_ms, 30000) });
    const stream = { frames: [] };
    const capture = createCapture(stream, (frame, event) => {
      for (const key of ["tool_call_id", "activity_id"]) if (event[key]) frame[key] = event[key];
      delete frame.observer_receipt_node_ms;
    });
    capture.feed(Buffer.from(read.body));
    capture.finish();
    return { ...read, body: undefined, frames: stream.frames };
  }
  async function nativeProof(turn) {
    await guard("navigation_native_proof");
    const script = fileURLToPath(new URL("./joint_navigation_cases.py", import.meta.url));
    const output = await runNativeCheck({ python: config.python, args: [script, "--native-check"],
      input: JSON.stringify({ conversation_key: turn.conversation_key, run_id: turn.run_id }),
      timeoutMs: 7000, maxBytes: 32768, label: "navigation_native_proof", windows: config.native_windows });
    return JSON.parse(output);
  }
  async function finish({ turn }) {
    try {
      if (faultTask) await faultTask;
      if (ackTask) await ackTask;
      assert.equal(observerError, false);
      result.native_before = await nativeProof(turn);
      if (caseId === "frame_disconnect") {
        const baseline = await readBrowser(turn.turn_id, 0, false);
        assert.ok(baseline.eof && baseline.frames.length > 0 && baseline.frames.length <= 256);
        const cursors = baseline.frames.map((f) => f.cursor);
        assert.deepEqual(cursors, [...new Set(cursors)].sort((a, b) => a - b));
        const restored = [], cuts = [];
        for (let i = 0; i < baseline.frames.length; i += 1) {
          await guard("navigation_frame_replay");
          const cut = await readBrowser(turn.turn_id, i ? cursors[i - 1] : 0, true);
          assert.equal(cut.frames.length, 1);
          assert.deepEqual(cut.frames[0], baseline.frames[i]);
          assert.ok(cut.abort_called && cut.reader_cancelled && cut.request_started);
          restored.push(cut.frames[0]);
          const next = await readBrowser(turn.turn_id, cursors[i], true);
          assert.deepEqual(next.frames, i + 1 < cursors.length ? [baseline.frames[i + 1]] : []);
          if (i + 1 === cursors.length) assert.ok(next.eof);
          cuts.push({ cut_cursor: cursors[i], next_cursor: next.frames[0]?.cursor ?? null,
            request_started: cut.request_started, abort_called: cut.abort_called,
            reader_cancelled: cut.reader_cancelled });
        }
        result.frame_disconnect = { scope: "native_browser_per_frame_cancel_replay_and_live_ui_fault",
          baseline: baseline.frames, restored, cuts, real_eof: baseline.eof,
          ui_transport_failed: transportFailed, ui_reconnected: reconnected,
          no_duplicate_tools: true };
      } else {
        const activities = await page.locator("[data-activity-id]").evaluateAll((nodes) => nodes.map((n) => n.dataset.activityId));
        assert.ok(activities.length > 0, "actual tool activity DOM required");
        result.navigation.dom_tool_count = activities.length;
        result.navigation.no_duplicate_dom_tools = activities.length === new Set(activities).size;
        const b = await page.evaluate(async (key) => {
          const response = await fetch(`/api/trench-ai/conversations/${encodeURIComponent(key)}/snapshot`,
            { credentials: "include", cache: "no-store" });
          if (!response.ok) throw new Error("B snapshot failed");
          return (await response.json()).data;
        }, seed.b_key);
        assert.ok(!b.active_turn && !b.latest_turn, "navigation must not admit a B turn");
      }
      const after = await nativeProof(turn);
      assert.deepEqual(after, result.native_before, "observer probes changed canonical tools/admission");
      const writes = requests.filter((r) => !["GET", "HEAD", "OPTIONS"].includes(r.method));
      assert.equal(writes.filter((r) => /\/turns$/.test(r.path)).length, 1);
      assert.ok(writes.every((r) => r.path === "/api/trench-ai/conversations" || /\/conversations\/[^/]+\/turns$/.test(r.path)),
        "navigation must not pause/cancel/resume/update the Turn");
      result.observe_only = true;
      await page.screenshot({ path: path.join(config.evidence_dir, `${caseId}-fault-final.png`) });
      return result;
    } finally {
      if (caseId === "navigation") {
        network.off("Fetch.requestPaused", pausedListener);
        await network.send("Fetch.disable");
      }
      await network.send("Network.emulateNetworkConditions", { offline: false, latency: 0,
        downloadThroughput: -1, uploadThroughput: -1 });
      network.off("Network.requestWillBeSent", requestListener);
      network.off("Network.loadingFailed", failedListener);
      network.off("Network.responseReceived", responseListener);
      network.off("Network.loadingFinished", finishedListener);
    }
  }
  const isExpectedFailure = (requestId) => injectedFailures.has(requestId)
    || faultWindow && streams.has(requestId);
  return { beforeSubmit, afterAdmission, onFrame, finish, isExpectedFailure };
}
