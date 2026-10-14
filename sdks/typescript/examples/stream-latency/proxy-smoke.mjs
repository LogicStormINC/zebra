import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { chromium } from "@playwright/test";
import { proxyStream, streamUpstream } from "./observer-proxy.mjs";

const path = "/agui/threads/00000000-0000-0000-0000-000000000001/runs/smoke/stream";
let observed, disconnected;
const upstream = createServer((request, response) => {
  observed = { url: request.url, headers: request.headers };
  if (request.url.startsWith(path.replace("smoke", "redirect"))) { response.writeHead(302, { Location: "/escaped" }).end(); return; }
  if (request.url === "/escaped") assert.fail("Proxy followed a redirect");
  response.writeHead(200, { "Content-Type": "text/event-stream" });
  response.write('data: {"type":"CUSTOM","name":"zebra.stream.recovery_complete","value":{}}\n\n');
  response.write('data: {"type":"CUSTOM","name":"zebra.stream.draft","value":{"message_id":"message:smoke","generation_id":"smoke","offset":0,"content_delta":"Controlled HTTP draft"}}\n\n');
  response.on("close", () => disconnected?.());
});
await new Promise(resolve => upstream.listen(0, "127.0.0.1", resolve));
const upstreamOrigin = `http://127.0.0.1:${upstream.address().port}`;
let target = streamUpstream(upstreamOrigin + path);
const proxy = createServer((request, response) => void proxyStream(request, response, target, origin));
await new Promise(resolve => proxy.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${proxy.address().port}`;
const headers = { Authorization: "Bearer synthetic-smoke-only", "Last-Event-ID": "synthetic-cursor", Origin: origin, "X-Zebra-Client-Session": "must-not-forward" };
try {
  for (const invalid of ["https://127.0.0.1" + path, "http://example.com" + path, upstreamOrigin + path + "?token=bad", upstreamOrigin + "/anything", `http://user:password@127.0.0.1:${upstream.address().port}${path}`]) assert.throws(() => streamUpstream(invalid));
  for (const suffix of ["?url=http://example.com", "?recovery=bad", "?recovery=full&recovery=full", "/elsewhere"]) assert.equal((await fetch(origin + "/observer/stream" + suffix, { headers })).status, 400);
  assert.equal((await fetch(origin + "/observer/stream", { method: "POST", headers })).status, 400);
  assert.equal((await fetch(origin + "/observer/stream", { headers: { ...headers, Origin: "https://unapproved.invalid" } })).status, 400);
  assert.equal((await fetch(origin + "/observer/stream")).status, 401);
  assert.equal(observed, undefined);
  const closed = new Promise(resolve => { disconnected = resolve; });
  const response = await fetch(origin + "/observer/stream?recovery=full", { headers });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  const reader = response.body.getReader();
  assert(new TextDecoder().decode((await reader.read()).value).includes("recovery_complete"));
  assert.equal(observed.url, path + "?recovery=full");
  assert.equal(observed.headers.authorization, headers.Authorization);
  assert.equal(observed.headers["last-event-id"], headers["Last-Event-ID"]);
  assert.equal(observed.headers.origin, undefined);
  assert.equal(observed.headers["x-zebra-client-session"], undefined);
  await reader.cancel();
  await Promise.race([closed, new Promise((_, reject) => { const timer = setTimeout(() => reject(new Error("Upstream disconnect was not cancelled")), 2000); timer.unref(); })]);
  target = streamUpstream(upstreamOrigin + path.replace("smoke", "redirect"));
  assert.equal((await fetch(origin + "/observer/stream", { headers })).status, 502);
  const child = spawn(process.execPath, [new URL("run.mjs", import.meta.url).pathname, "--stream-grant-stdin"], { stdio: ["pipe", "pipe", "pipe"] });
  let output = "", browser;
  try {
    const ready = new Promise((resolve, reject) => {
      child.once("error", reject);
      child.once("exit", () => reject(new Error("stdin runner exited before readiness")));
      child.stdout.on("data", chunk => { output += chunk; const match = output.match(/http:\/\/127\.0\.0\.1:\d+/); if (match) resolve(match[0]); });
    });
    child.stdin.end(JSON.stringify({ upstream: upstreamOrigin + path, grant: "synthetic-stdin-grant-only" }) + "\n");
    const childOrigin = await ready;
    const html = await (await fetch(childOrigin)).text();
    assert(!html.includes("synthetic-stdin-grant-only"));
    assert(html.includes('data-observer-grant="stdin"'));
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    await page.goto(childOrigin);
    assert(await page.getByRole("checkbox", { name: "Observer only" }).isChecked());
    assert(await page.locator('[name="hostGrant"]').isDisabled());
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await page.waitForFunction(() => Number(document.querySelector("output").dataset.firstBodyMs) > 0);
    assert.equal(await page.locator('[data-presentation="provisional"]').textContent(), "Controlled HTTP draft");
    assert.equal(observed.headers.authorization, "Bearer synthetic-stdin-grant-only");
    assert.equal(observed.headers["x-zebra-client-session"], undefined);
    assert.equal(observed.headers.origin, undefined);
    assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0);
    assert(!output.includes("synthetic-stdin-grant-only"));
    await page.getByRole("button", { name: "Stop", exact: true }).click();
  } finally {
    await browser?.close();
    const exited = once(child, "exit");
    child.kill("SIGTERM");
    await exited;
  }
  console.log("Fixed loopback SSE proxy smoke passed: auth/cursor forwarding, query/path/origin guards, redirect rejection and disconnect cancellation (no model)");
} finally {
  proxy.closeAllConnections();
  upstream.closeAllConnections();
  await Promise.all([new Promise(resolve => proxy.close(resolve)), new Promise(resolve => upstream.close(resolve))]);
}
