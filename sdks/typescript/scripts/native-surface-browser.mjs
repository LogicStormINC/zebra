import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { createServer, get } from "node:http";
import { mkdtemp, mkdir, readFile, writeFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, webkit } from "@playwright/test";
import { readableFixtureSource, exerciseReadables } from "./native-readable-browser.mjs";
import { createNativeSurfaceBff } from "./native-surface-bff.mjs";
const sdk = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repo = resolve(sdk, "../..");
const work = await mkdtemp(join(tmpdir(), "native-surface-"));
const container = "ca-surface-" + process.pid + "-" + Date.now();
let nativeProcess, server;
const reports = [];
const readable = process.env.ZEBRA_NATIVE_READABLE_ACCEPTANCE === "1";
function run(command, args, cwd = repo) { return new Promise((ok, fail) => { const child = spawn(command, args, { cwd, stdio: "inherit" }); child.on("error", fail); child.on("exit", code => code === 0 ? ok() : fail(new Error(`${command} failed: ${code}`))); }); }
async function until(read, message) { for (let n = 0; n < 200; n++) { try { const value = await read(); if (value) return value; } catch {} await new Promise(r => setTimeout(r, 100)); } throw new Error(message); }
try {
  await run("docker", ["run", "--detach", "--name", container, "-e", "POSTGRES_PASSWORD=fixture", "-e", "POSTGRES_DB=fixture", "-p", "127.0.0.1::5432", "postgres:17-alpine"]);
  await until(() => { execFileSync("docker", ["exec", container, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"], { stdio: "ignore" }); return true; }, "owned PG readiness");
  const port = execFileSync("docker", ["port", container, "5432/tcp"], { encoding: "utf8" }).trim().split(":").at(-1);
  const web = join(work, "web"); const packs = join(work, "packs"); await mkdir(web); await mkdir(packs);
  const deps = { react: "19.2.8", "react-dom": "19.2.8", vite: "6.4.3", zod: "4.4.3" };
  for (const pkg of ["contracts", "ui-contracts", "client-core", "react"]) {
    const before = await readdir(packs); await run("pnpm", ["pack", "--pack-destination", packs], join(sdk, "packages", pkg));
    const file = (await readdir(packs)).find(f => !before.includes(f)); deps[`@zebra-agent/${pkg}`] = `file:${join(packs, file)}`;
  }
  await writeFile(join(web, "package.json"), JSON.stringify({ private: true, dependencies: deps, pnpm: { overrides: Object.fromEntries(Object.entries(deps).filter(([k]) => k.startsWith("@zebra-agent/"))) } }));
  await run("pnpm", ["install", "--ignore-workspace", "--no-frozen-lockfile", "--strict-peer-dependencies"], web);
  await writeFile(join(web, "tsconfig.json"), JSON.stringify({ compilerOptions: { jsx: "react-jsx" } }));
  await writeFile(join(web, "index.html"), '<div id="root"></div><script type="module" src="/main.tsx"></script>');
  for (const [label, engine] of [["Chromium", chromium], ["WebKit", webkit]]) {
    const folder = join(work, label); await mkdir(folder);
    await writeFile(join(folder, "native-input.json"), JSON.stringify({ dsn: `postgresql://postgres:fixture@127.0.0.1:${port}/fixture`, ...(readable ? { readable: true } : {}) }), { mode: 0o600 });
    nativeProcess = spawn(join(repo, ".venv/bin/python"), ["-m", "tests.acceptance.native_surface_server", folder], { cwd: repo, env: Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^(ZEBRA_|OVERDOZE_|PG|AWS_|OPENAI_|DEEPSEEK_|PYTHONPATH$|HTTP_PROXY$|HTTPS_PROXY$|ALL_PROXY$)/i.test(key))), stdio: ["ignore", "pipe", "pipe"] });
    nativeProcess.stderr.on("data", data => { process.stderr.write(data); });
    const native = await until(async () => JSON.parse(await readFile(join(folder, "native-ready.json"), "utf8")), "native startup failed (inspect fixture stderr)");
    const bff = await createNativeSurfaceBff(native, join(folder, "mapping.json"));
    await writeFile(join(web, "main.tsx"), readable ? readableFixtureSource(bff.config, native.profile, native.commandRevision) : source(bff.config, native.profile));
    await run("pnpm", ["exec", "vite", "build"], web);
    server = createServer(async (req, res) => { if (await bff.handle(req, res)) return; if (req.url !== "/" && !/^\/assets\/[A-Za-z0-9_-]+\.js$/.test(req.url)) { res.writeHead(404); res.end(); return; } try { const file = join(web, "dist", req.url === "/" ? "index.html" : req.url); res.setHeader("content-type", file.endsWith(".js") ? "text/javascript" : "text/html"); res.end(await readFile(file)); } catch { res.writeHead(404); res.end(); } });
    await new Promise(r => server.listen(0, "127.0.0.1", r)); bff.state.origin = `http://127.0.0.1:${server.address().port}`;
    assert.equal(await new Promise((resolveStatus, reject) => { get(bff.state.origin, { path: `/../../${label}/mapping.json` }, response => { response.resume(); resolveStatus(response.statusCode); }).on("error", reject); }), 404);
    const browser = await engine.launch(); const page = await browser.newPage(); const errors = []; const wire = [];
    page.on("pageerror", error => errors.push(error.message)); page.on("response", async r => { if (r.url().includes("/api/agent/")) try { wire.push(await r.text()); } catch {} });
    try {
      await page.goto(bff.state.origin + "/fixture/login"); await page.goto(bff.state.origin);
      await page.locator("#status").filter({ hasText: "ready" }).waitFor().catch(error => { console.error({ errors, mounts: bff.state.mounts.length, responseCount: wire.length }); throw error; });
      const schedule = async itemId => { const r = await fetch(native.nativeUrl + "/fixture/schedule", { method: "POST", headers: { "X-Fixture-Key": native.fixtureKey, "Content-Type": "application/json" }, body: JSON.stringify({ itemId }) }); assert.equal(r.status, 200); };
      const first = bff.state.mounts.at(-1); assert.ok(first);
      await schedule("item-1"); await page.locator("#opened").filter({ hasText: "item-1" }).waitFor();
      await until(() => bff.state.replayed, "native receipt replay");
      await page.locator("#change").click();
      await until(() => bff.state.mounts.at(-1)?.ui_revision > first.ui_revision, "same-action remount");
      const second = bff.state.mounts.at(-1); assert.notEqual(first.binding_digest, second.binding_digest); assert.ok(second.binding_revision > first.binding_revision);
      await schedule("item-2"); await page.locator("#opened").filter({ hasText: "item-2" }).waitFor();
      const report = await until(async () => { const r = await fetch(native.nativeUrl + "/fixture/report", { headers: { "X-Fixture-Key": native.fixtureKey } }); const body = await r.json(); return body.receipts === 2 ? body : false; }, "two durable receipts");
      assert.equal(await page.locator("#count").textContent(), "2"); assert.deepEqual(report, { scheduled: 2, receipts: 2, resumes: 2 });
      assert.deepEqual(bff.state.receipts[0], bff.state.receipts[1]); assert.equal(await page.evaluate(() => document.cookie), "");
      const visible = JSON.stringify(wire) + JSON.stringify(bff.config) + await page.evaluate(() => JSON.stringify(sessionStorage) + document.documentElement.outerHTML);
      for (const secret of [native.credential, ...bff.state.fences]) assert.ok(!visible.includes(secret));
      const readableReport = readable ? await exerciseReadables(page, native, bff) : {};
      const before = bff.state.calls;
      assert.equal(await page.evaluate(async config => (await fetch(config.baseUrl + `/v1/client-sessions/${config.clientSessionId}/heartbeat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ task_id: "foreign" }) })).status, bff.config), 403);
      assert.equal((await page.request.post(bff.state.origin + bff.config.baseUrl + `/v1/client-sessions/${native.session}/heartbeat`, { headers: { Origin: "https://foreign.example" }, data: {} })).status(), 403);
      assert.equal(bff.state.calls, before);
      bff.state.authorized = false; await page.locator("#status").filter({ hasText: "stopped" }).waitFor();
      assert.deepEqual(errors, []); reports.push({ browser: label, ...report, ...readableReport, receiptReplay: true, remount: true, secretRedaction: true, unauthorizedStopped: true });
    } finally { await browser.close(); await new Promise(r => server.close(r)); server = undefined; nativeProcess.kill(); await new Promise(r => nativeProcess.once("exit", r)); nativeProcess = undefined; }
  }
  console.log(JSON.stringify({ contract: readable ? "sdk-readable-commands/1" : "sdk-surface-sync/1", boundary: "local compatibility HTTP; real PostgreSQL; Worker gateway and durable resume command; fixture business login", reports }, null, 2));
} finally { nativeProcess?.kill(); server?.close(); execFileSync("docker", ["rm", "-f", "-v", container], { stdio: "ignore" }); await rm(work, { recursive: true, force: true }); }
function source(config, profile) { return `
import {createElement,StrictMode,useState} from 'react'; import {createRoot} from 'react-dom/client'; import {z} from 'zod';
import {ZebraAgentProvider,useZebraAction,useZebraReadable,useZebraClientStatus} from '@zebra-agent/react';
const config=${JSON.stringify(config)};
function Panel(){const [route,setRoute]=useState('/items');const [opened,setOpened]=useState('');const [count,setCount]=useState(0);
useZebraReadable('app.ui.route',{route});useZebraAction('app.ui.item.open',{parameters:z.object({itemId:z.string()}),result:z.object({opened:z.boolean()}),handler:({itemId})=>{setOpened(itemId);setCount(n=>n+1);return {opened:true}}});
return <><output id="status">{useZebraClientStatus()}</output><output id="opened">{opened}</output><output id="count">{count}</output><button id="change" onClick={()=>setRoute('/other')}>Change route</button></>}
createRoot(document.getElementById('root')).render(<StrictMode><ZebraAgentProvider config={config} frontendAppId=${JSON.stringify(profile.frontend_app_id)} profileRevision={${profile.revision}} profileDigest=${JSON.stringify(profile.profile_digest)}><Panel/></ZebraAgentProvider></StrictMode>);
`; }
