import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
import { proxyStream, streamUpstream } from "./observer-proxy.mjs";
import { createInterface } from "node:readline";
const upstreamIndex = process.argv.indexOf("--stream-upstream");
let upstream = upstreamIndex < 0 ? null : streamUpstream(process.argv[upstreamIndex + 1]);
let streamGrant;
if (process.argv.includes("--stream-grant-stdin")) {
  if (upstream) throw new Error("Choose stream-upstream or stream-grant-stdin");
  const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
  try {
    const { value: line } = await input[Symbol.asyncIterator]().next();
    if (typeof line !== "string" || line.length > 32768) throw new Error();
    const value = JSON.parse(line);
    if (!value || Object.keys(value).sort().join(",") !== "grant,upstream" || typeof value.grant !== "string" || !value.grant || /\s/.test(value.grant) || value.grant.length > 16377 || typeof value.upstream !== "string") throw new Error();
    upstream = streamUpstream(value.upstream);
    streamGrant = value.grant;
  } catch { throw new Error("Invalid stream grant stdin payload"); }
  finally { input.close(); process.stdin.pause(); }
}
const require = createRequire(new URL("../../package.json", import.meta.url));
const esbuild = require(require.resolve("esbuild", { paths: [dirname(require.resolve("tsx/package.json"))] }));
const output = await mkdtemp(join(tmpdir(), "zebra-stream-example-"));
const build = await esbuild.build({
  entryPoints: [fileURLToPath(new URL("app.tsx", import.meta.url))], bundle: true,
  outfile: join(output, "app.js"), platform: "browser", format: "esm", metafile: true,
  nodePaths: [fileURLToPath(new URL("../../packages/react/node_modules", import.meta.url)), fileURLToPath(new URL("../../packages/react-charts/node_modules", import.meta.url))],
});
assert(Object.keys(build.metafile.inputs).some(path => path.includes("client-core/dist/")), "client-core must consume built exports");
assert(Object.keys(build.metafile.inputs).some(path => path.includes("react/dist/")), "react must consume built exports");
assert(!Object.keys(build.metafile.inputs).some(path => /packages\/(client-core|react|contracts|ui-contracts)\/src\//.test(path)), "example must not import SDK sources");
const html = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cloud Agent stream diagnostics</title><link rel="stylesheet" href="/app.css"><div id="root" data-observer-grant="' + (streamGrant ? 'stdin' : 'form') + '"></div><script type="module" src="/app.js"></script></html>';
const server = createServer(async (request, response) => {
  const path = request.url?.split("?")[0];
  if (path === "/observer/stream") { await proxyStream(request, response, upstream, `http://127.0.0.1:${server.address().port}`, streamGrant); return; }
  if (request.method !== "GET") { response.writeHead(405).end(); return; }
  if (path === "/") { response.setHeader("Content-Type", "text/html"); response.end(html); return; }
  if (path !== "/app.js" && path !== "/app.css") { response.writeHead(404).end(); return; }
  response.setHeader("Content-Type", path.endsWith(".css") ? "text/css" : "text/javascript");
  response.end(await readFile(join(output, path.slice(1))));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
if (process.argv.includes("--check")) {
  let browser;
  try {
    for (const path of ["/", "/app.js", "/app.css"]) {
      const response = await fetch(`${origin}${path}`);
      assert.equal(response.status, 200);
      assert((await response.text()).length > 0);
    }
    assert.equal((await fetch(`${origin}/unknown`)).status, 404);
    browser = await require("@playwright/test").chromium.launch({ headless: true });
    const page = await browser.newPage();
    await page.goto(origin);
    await page.getByRole("button", { name: "Replay stream", exact: true }).click();
    await page.waitForFunction(() => Number(document.querySelector("output").dataset.firstBodyMs) > 0);
    assert.equal(await page.locator('.zebra-agent-message__draft').count(), 1);
    await page.getByRole("button", { name: "Commit final", exact: true }).click();
    await page.waitForFunction(() => Number(document.querySelector("output").dataset.committedBodyMs) > 0);
    assert.equal(await page.locator('.zebra-agent-message__draft').count(), 0);
    await page.addInitScript(() => {
      const original = window.fetch.bind(window);
      window.fetch = async (input, init) => {
        if (!String(input).startsWith("https://observer.invalid")) return original(input, init);
        window.observerHeaders = init.headers;
        if (!String(input).includes("/stream")) return Response.json({ effects: [] });
        return new Response(new ReadableStream({ start(controller) {
          window.observerController = controller;
          const frame = (name, value) => new TextEncoder().encode(`data: ${JSON.stringify({ type: "CUSTOM", name, value })}\n\n`);
          controller.enqueue(frame("zebra.stream.recovery_complete", {}));
          controller.enqueue(frame("zebra.stream.draft", { message_id: "message:live", generation_id: "check", offset: 0, content_delta: "Live draft" }));
        }}), { headers: { "Content-Type": "text/event-stream" } });
      };
    });
    await page.reload();
    await page.locator('[name="baseUrl"]').fill("https://observer.invalid");
    await page.locator('[name="clientSessionId"]').fill("example");
    await page.locator('[name="sessionCredential"]').fill("example:synthetic-secret-only");
    await page.locator('[name="streamUrl"]').fill("/stream");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await page.waitForFunction(() => Number(document.querySelector("output").dataset.firstBodyMs) > 0);
    assert.equal(await page.locator('[name="sessionCredential"]').inputValue(), "");
    assert.equal(await page.locator('[data-presentation="provisional"]').textContent(), "Live draft");
    const state = await page.evaluate(() => ({ headers: window.observerHeaders, local: localStorage.length, session: sessionStorage.length }));
    assert(Object.values(state.headers).includes("example:synthetic-secret-only"));
    assert.equal(state.local, 0);
    assert.equal(state.session, 0);
    await page.evaluate(() => window.observerController.enqueue(new TextEncoder().encode(`data: ${JSON.stringify({ type: "CUSTOM", name: "zebra.answer_committed", value: { model_call_id: "live", assistant_message: "Live final" } })}\n\n`)));
    await page.waitForFunction(() => Number(document.querySelector("output").dataset.committedBodyMs) > 0);
    assert.equal(await page.locator('[data-presentation="committed"]').textContent(), "Live final");
    await page.getByRole("button", { name: "Stop", exact: true }).click();
    await page.reload();
    await page.getByRole("checkbox", { name: "Observer only" }).check();
    await page.locator('[name="baseUrl"]').fill("https://observer.invalid");
    await page.locator('[name="streamUrl"]').fill("/stream");
    await page.locator('[name="hostGrant"]').fill("synthetic-host-grant-only");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await page.waitForFunction(() => Number(document.querySelector("output").dataset.firstBodyMs) > 0);
    assert.equal(await page.locator('[name="hostGrant"]').inputValue(), "");
    const observer = await page.evaluate(() => ({ authorization: new Headers(window.observerHeaders).get("Authorization"), session: new Headers(window.observerHeaders).get("X-Zebra-Client-Session"), stored: localStorage.length + sessionStorage.length }));
    assert.equal(observer.authorization, "Bearer synthetic-host-grant-only");
    assert.equal(observer.session, null);
    assert.equal(observer.stored, 0);
    await page.getByRole("button", { name: "Stop", exact: true }).click();
    await page.addInitScript(() => {
      const original = window.fetch.bind(window);
      let streams = 0, polls = 0;
      window.fetch = async (input, init) => {
        if (!String(input).startsWith("https://race.invalid")) return original(input, init);
        if (String(input).includes("/effects")) {
          if (++polls === 1) return new Promise(resolve => { window.releaseOldPoll = () => resolve(Response.json({ effects: [] })); });
          return Response.json({ effects: [] });
        }
        if (!String(input).includes("/stream")) return new Response(null, { status: 503 });
        const old = ++streams === 1;
        return new Response(new ReadableStream({ start(controller) {
          const frame = (name, value) => new TextEncoder().encode(`data: ${JSON.stringify({ type: "CUSTOM", name, value })}\n\n`);
          // One buffered read: recovery awaits the old pending-effects poll before draft delivery.
          const recovery = frame("zebra.stream.recovery_complete", {});
          const draft = frame("zebra.stream.draft", { message_id: old ? "message:old" : "message:new", generation_id: "race", offset: 0, content_delta: old ? "STALE BUFFERED DRAFT" : "Current connection draft" });
          const batch = new Uint8Array(recovery.length + draft.length);
          batch.set(recovery); batch.set(draft, recovery.length);
          controller.enqueue(batch);
        }}), { headers: { "Content-Type": "text/event-stream" } });
      };
    });
    await page.reload();
    await page.locator('[name="baseUrl"]').fill("https://race.invalid");
    await page.locator('[name="clientSessionId"]').fill("race");
    await page.locator('[name="sessionCredential"]').fill("race:synthetic-secret-only");
    await page.locator('[name="streamUrl"]').fill("/stream");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await page.waitForFunction(() => typeof window.releaseOldPoll === "function");
    await page.getByRole("button", { name: "Stop", exact: true }).click();
    await page.locator('[name="sessionCredential"]').fill("race:synthetic-secret-only");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await page.waitForFunction(() => Number(document.querySelector("output").dataset.firstBodyMs) > 0);
    const currentTiming = await page.locator("output").getAttribute("data-first-observation-ms");
    await page.evaluate(async () => { window.releaseOldPoll(); await new Promise(resolve => setTimeout(resolve, 50)); });
    assert.equal(await page.locator('[data-presentation="provisional"]').textContent(), "Current connection draft");
    assert.equal(await page.locator("output").getAttribute("data-first-observation-ms"), currentTiming);
    await page.getByRole("button", { name: "Stop", exact: true }).click();
    console.log("Stream diagnostics built-export/routes/replay/form observer check passed (synthetic frames; no backend/model)");
  } finally {
    await browser?.close();
    await new Promise(resolve => server.close(resolve));
    await rm(output, { recursive: true, force: true });
  }
} else console.log(`Standalone stream diagnostics: ${origin}`);
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => { streamGrant = undefined; upstream = null; server.close(); void rm(output, { recursive: true, force: true }).finally(() => process.exit()); });
