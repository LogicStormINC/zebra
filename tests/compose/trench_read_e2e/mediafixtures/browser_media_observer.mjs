// Observation of genuine browser/SSE media. No DOM replacement or fulfilled responses.
import assert from "node:assert/strict";
import path from "node:path";

export async function startMediaObserver({ page, caseId, config, guard }) {
  assert.ok(["image", "inline_video", "chart_markdown_latex", "revision"].includes(caseId));
  assert.equal(typeof guard, "function");
  // The Host's ordered-item adapter renders media outside its inner text wrapper.
  const root = ".zebra-agent-message--assistant";
  const base = new URL(config.base_url).origin;
  const admitted = page.waitForResponse((r) => r.request().method() === "POST"
    && /\/conversations\/[^/]+\/turns$/.test(new URL(r.url()).pathname),
  { timeout: config.timeout_ms }).then(async (r) => {
    assert.equal(r.status(), 202);
    return (await r.json()).data.turn;
  });
  // Promise rejection is reported by finish; no unhandled background task.
  admitted.catch(() => {});
  const result = { scope: "actual_browser_media_observation", fixture_provider: false };
  const tasks = [];
  const replacements = [];
  let finalReceived = false;
  let started = false;
  let beforeVideo;
  let videoHandle;
  let anchorHandle;
  let anchorTop;
  let faultAborted = false;
  let faultAsset;
  let downloadRequests = 0;
  let failed = false;
  let observationStage = "awaiting_frame";
  let failureStage;
  const observeRequest = (request) => {
    if (/\/assets\/[^/]+\/[^/]+\/download(?:\?|$)/.test(request.url())) downloadRequests += 1;
  };
  page.on("request", observeRequest);
  const faultHandler = async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== base || request.method() !== "GET" || request.resourceType() !== "image") {
      return route.fallback();
    }
    const fault = page.locator(`${root} img[alt="QA_IMAGE_FAULT"]`);
    const target = faultAsset || (await fault.count() === 1 ? await fault.getAttribute("src") : null);
    if (target && new URL(target, base).href === request.url()) {
      await guard("media_fault");
      faultAborted = true;
      return route.abort("failed");
    }
    return route.fallback();
  };
  if (caseId === "image") await page.route("**/api/trench-ai/assets/**", faultHandler);
  const enqueue = (work) => {
    const task = work().catch(() => { failed = true; failureStage ??= observationStage; });
    tasks.push(task);
    assert.ok(tasks.length <= 256);
  };
  async function visibility() {
    observationStage = "preterminal_visibility";
    const beforeReceipt = !finalReceived;
    const turn = await admitted;
    const state = await page.evaluate(async (id) => {
      const response = await fetch(`/api/trench-ai/turns/${encodeURIComponent(id)}`,
        { credentials: "include", cache: "no-store" });
      if (!response.ok) return false;
      return ["accepted", "queued", "dispatching", "running"]
        .includes((await response.json()).data?.turn?.status);
    }, turn.turn_id);
    result.preterminal = { before_terminal: state, before_final_receipt: beforeReceipt && !finalReceived };
    assert.ok(state && beforeReceipt && !finalReceived, "media must render during execution");
    await page.screenshot({ path: path.join(config.evidence_dir, `${caseId}-preterminal.png`) });
  }
  async function initial() {
    if (caseId === "image") {
      observationStage = "image_locator";
      const image = page.locator(`${root} img[alt="QA_IMAGE_GOOD"]`).first();
      await image.scrollIntoViewIfNeeded();
      observationStage = "image_decode";
      await image.evaluate((node) => node.decode());
      assert.ok(await image.evaluate((node) => node.complete && node.naturalWidth > 0));
      result.image = { decoded: true };
    } else if (caseId === "chart_markdown_latex") {
      observationStage = "chart_visibility";
      const good = page.locator(`${root} .zebra-agent-chart`).filter({ hasText: "QA_CHART_GOOD" });
      await good.locator("svg").waitFor({ state: "visible" });
      result.chart = { valid_svg: true };
    } else {
      observationStage = "video_playback";
      const video = page.locator(`${root} video`).first();
      await video.waitFor({ state: "visible" });
      await video.scrollIntoViewIfNeeded();
      videoHandle = await video.elementHandle();
      assert.ok(videoHandle);
      assert.equal(await video.evaluate((v) => v.currentSrc || v.querySelector("source")?.src),
        config.media_fixture.video_url, "only the verified original video can close this case");
      await video.evaluate(async (v) => { v.muted = true; v.loop = true; await v.play(); });
      beforeVideo = await video.evaluate((v) => ({ time: v.currentTime,
        frames: v.getVideoPlaybackQuality().totalVideoFrames }));
      await page.waitForFunction(({ selector, before }) => {
        const v = document.querySelector(selector);
        return v instanceof HTMLVideoElement && !v.paused && !v.error
          && v.currentTime - before.time >= 0.2
          && v.getVideoPlaybackQuality().totalVideoFrames - before.frames >= 2;
      }, { selector: `${root} video`, before: beforeVideo }, { timeout: 10000 });
      const playing = await video.evaluate((v) => ({ time: v.currentTime,
        frames: v.getVideoPlaybackQuality().totalVideoFrames }));
      result.video = { played: true, source_kind: "verified_external_direct",
        time_advanced_seconds: playing.time - beforeVideo.time,
        frames_advanced: playing.frames - beforeVideo.frames };
      anchorHandle = await video.evaluateHandle((v) => v.closest("figure") || v.parentElement);
      anchorTop = await anchorHandle.evaluate((node) => node.getBoundingClientRect().top);
    }
    await visibility();
    observationStage = "initial_observation_complete";
  }
  function onFrame(frame, event) {
    if (caseId === "image") {
      const part = event.content_parts?.find((part) => part.type === "image" &&
        (part.alt === "QA_IMAGE_FAULT" || part.fileName === `${config.media_fixture?.event_id}-image-2.jpg`));
      if (typeof part?.artifactId === "string" && /^\/api\/trench-ai\/assets\/[0-9a-f-]{36}\/[0-9a-f-]{36}$/i.test(part.artifactId)) {
        faultAsset = `${part.artifactId}/preview`;
      }
    }
    if (event.answer_committed === true) finalReceived = true;
    if (!started && !finalReceived) {
      started = true;
      enqueue(initial);
    }
    if (caseId === "revision" && event.type === "public_output" && event.replaces_output_id) {
      assert.equal(typeof event.output_id, "string");
      replacements.push({ output_id: event.output_id, replaces_output_id: event.replaces_output_id,
        cursor: frame.cursor, before_final_receipt: !finalReceived });
      // Await the genuine changed DOM, then compare retained node references. Never rerender it.
      enqueue(async () => {
        assert.ok(videoHandle && anchorHandle && result.preterminal,
          "revision received before live playback: sample cannot prove stability");
        await page.locator(`${root} details`).filter({ hasText: "此前结果" }).first()
          .waitFor({ state: "visible" });
        const state = await videoHandle.evaluate((v) => ({ connected: v.isConnected,
          time: v.currentTime, paused: v.paused, frames: v.getVideoPlaybackQuality().totalVideoFrames }));
        const sameNode = await page.locator(`${root} video`).first().evaluate((v, old) => v === old, videoHandle);
        const anchor = await anchorHandle.evaluate((node) => ({ connected: node.isConnected,
          top: node.getBoundingClientRect().top }));
        result.revision = { canonical_replacement: true, same_video_node: sameNode && state.connected,
          playback_continued: !state.paused && state.time > beforeVideo.time
            && state.frames > beforeVideo.frames,
          reader_anchor: anchor.connected && Math.abs(anchor.top - anchorTop) <= 2,
          anchor_shift_px: Math.abs(anchor.top - anchorTop), replacements };
      });
    }
  }
  async function finish({ frames }) {
    try {
      await Promise.all(tasks);
      assert.equal(failed, false, "live media/revision observation failed");
      assert.ok(started && result.preterminal);
      if (caseId === "image") {
        observationStage = "image_fault_isolation";
        assert.ok(faultAborted, "actual browser failure was not exercised");
        const good = page.locator(`${root} img[alt="QA_IMAGE_GOOD"]`).first();
        const bad = page.locator(`${root} img[alt="QA_IMAGE_FAULT"]`).first();
        assert.ok(await bad.evaluate((img) => img.complete && img.naturalWidth === 0));
        result.image = { ...result.image, fault_aborted: faultAborted,
          sibling_survived: await good.evaluate((img) => img.isConnected && img.naturalWidth > 0) };
      }
      if (caseId === "chart_markdown_latex") {
        const bad = page.locator(`${root} .zebra-agent-chart`).filter({ hasText: "QA_CHART_FAULT" });
        await bad.getByRole("button", { name: "Retry chart" }).waitFor();
        assert.ok(await page.locator(`${root} .zebra-agent-chart`).filter({ hasText: "QA_CHART_GOOD" })
          .locator("svg").isVisible());
        result.chart = { ...result.chart, isolated_failure: true,
          markdown_table: await page.locator(`${root} table`).filter({ hasText: "Growth" }).first().isVisible(),
          latex_rendered: await page.locator(`${root} .katex`).first().isVisible() };
      }
      if (result.video) result.video.download_requests = downloadRequests;
      if (caseId === "revision") {
        assert.ok(result.revision && replacements.length > 0);
        assert.ok(replacements.every((r) => r.before_final_receipt && frames.some((f) => f.cursor === r.cursor)));
        assert.ok(result.revision.same_video_node && result.revision.playback_continued && result.revision.reader_anchor);
      }
      return result;
    } finally {
      page.off("request", observeRequest);
      if (caseId === "image") await page.unroute("**/api/trench-ai/assets/**", faultHandler);
      await videoHandle?.dispose();
      await anchorHandle?.dispose();
    }
  }
  return { onFrame, finish, evidence: () => ({ ...result, observation_stage: observationStage,
    failure_stage: failureStage, observation_failed: failed, fault_aborted: faultAborted,
    final_received: finalReceived }) };
}
