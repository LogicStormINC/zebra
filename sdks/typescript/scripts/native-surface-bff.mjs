import { randomUUID } from "node:crypto";
import { readFile, writeFile, rename, open } from "node:fs/promises";
import { publicClientSurfaceMetadata } from "../packages/client-core/dist/index.js";

/** ponytail: single-host test adapter only; production needs shared CAS storage and business auth. */
export async function createNativeSurfaceBff(native, mappingFile) {
  const login = randomUUID();
  const state = { origin: "", authorized: true, calls: 0, mounts: [], receipts: [], replayed: false, releases: 0, fences: [native.metadata.controller_fence_token] };
  let busy = false;
  const prefix = "/api/agent/surfaces/reference";
  async function save(value) {
    const tmp = mappingFile + ".tmp";
    await writeFile(tmp, JSON.stringify(value), { mode: 0o600 });
    const file = await open(tmp, "r+"); try { await file.sync(); } finally { await file.close(); }
    await rename(tmp, mappingFile);
    const dir = await open(new URL(".", `file://${mappingFile}`).pathname, "r");
    try { await dir.sync(); } finally { await dir.close(); }
  }
  await writeFile(mappingFile, "", { flag: "wx", mode: 0o600 });
  await save({ phase: "active", metadata: native.metadata });
  const config = { mode: "bff", surfaceMetadataVersion: 1, baseUrl: prefix, clientSessionId: native.session,
    controller: true, taskId: native.task, runId: "run-1", runBindingId: native.metadata.binding_id,
    clientBindingDigest: native.metadata.binding_digest, actionContractDigests: native.metadata.action_contract_digests,
    initialUiRevision: native.metadata.ui_revision };
  const reply = (res, code, body) => { res.writeHead(code, { "content-type": "application/json", "cache-control": "no-store" }); res.end(JSON.stringify(body)); };
  async function handle(req, res) {
    if (req.url === "/fixture/login") { res.setHeader("set-cookie", `business=${login}; HttpOnly; SameSite=Strict; Path=/`); reply(res, 200, {}); return true; }
    if (!req.url?.startsWith(prefix + "/")) return false;
    if (!state.authorized || req.headers.cookie !== `business=${login}`) { reply(res, 401, {}); return true; }
    if (req.method === "POST" && req.headers.origin !== state.origin || ["authorization", "x-zebra-client-session", "x-zebra-client-fence"].some(k => req.headers[k])) { reply(res, 403, {}); return true; }
    const path = req.url.slice(prefix.length);
    const sessionPrefix = `/v1/client-sessions/${native.session}/`;
    const action = path.startsWith(sessionPrefix) ? path.slice(sessionPrefix.length) : /^\/v1\/client-effects\/[0-9a-f-]{36}\/receipts$/.test(path) ? "receipts" : "";
    if (!["mount", "effects", "heartbeat", "release", "receipts"].includes(action)) { reply(res, 404, {}); return true; }
    if (req.method !== (action === "effects" ? "GET" : "POST")) { reply(res, 405, {}); return true; }
    const chunks = []; let size = 0;
    for await (const chunk of req) { size += chunk.length; if (size > 65536) { reply(res, 413, {}); return true; } chunks.push(chunk); }
    let body;
    try { body = size ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : {}; } catch { reply(res, 400, {}); return true; }
    if (!body || typeof body !== "object" || Array.isArray(body) ||
      body.task_id && body.task_id !== native.task || body.run_id && body.run_id !== "run-1" ||
      body.client_session_id && body.client_session_id !== native.session || body.controller === false) { reply(res, 403, {}); return true; }
    if (busy) { reply(res, 409, {}); return true; }
    busy = true;
    try {
      // Re-read persisted mapping for every request; restart/reconciliation needs a separate trusted protocol.
      const mapping = JSON.parse(await readFile(mappingFile, "utf8"));
      if (mapping.phase !== "active") { reply(res, 409, {}); return true; }
      const headers = { "Content-Type": "application/json", "X-Zebra-Client-Session": native.credential };
      if (action !== "mount" && action !== "effects") headers["X-Zebra-Client-Fence"] = mapping.metadata.controller_fence_token;
      if (req.headers["idempotency-key"]) headers["Idempotency-Key"] = req.headers["idempotency-key"];
      if (action === "mount") await save({ ...mapping, phase: "mounting" });
      state.calls++;
      const response = await fetch(native.nativeUrl + (action === "mount" ? native.path : path), {
        method: req.method, headers, signal: AbortSignal.timeout(5000),
        ...(req.method === "POST" ? { body: JSON.stringify(action === "mount" ? { mount: body, task_capability_scope: ["app.ui.item.open"], controller: true } : body) } : {}),
      });
      const result = await response.json();
      if (!response.ok) { reply(res, response.status, {}); return true; }
      if (action === "mount") {
        const publicValue = publicClientSurfaceMetadata(result);
        if (typeof result.controller_fence_token !== "string") throw new Error("missing server fence");
        await save({ phase: "active", metadata: result }); state.fences.push(result.controller_fence_token); state.mounts.push(publicValue); reply(res, 200, publicValue);
      } else if (action === "receipts") {
        state.receipts.push({ body, key: req.headers["idempotency-key"] }); state.replayed ||= result.replayed === true;
        reply(res, state.receipts.length === 1 ? 503 : 200, result);
      } else { if (action === "release") state.releases++; reply(res, response.status, result); }
    } catch { reply(res, 503, {}); } finally { busy = false; }
    return true;
  }
  return { state, config, handle };
}
