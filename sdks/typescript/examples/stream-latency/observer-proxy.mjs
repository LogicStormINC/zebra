import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";

export function streamUpstream(value) {
  const url = new URL(value);
  if (url.protocol !== "http:" || !["127.0.0.1", "[::1]"].includes(url.hostname) || url.username || url.password || url.search || url.hash || !/^\/agui\/threads\/[0-9a-f-]{36}\/runs\/[A-Za-z0-9_-]+\/stream$/i.test(url.pathname)) {
    throw new Error("Stream upstream must be a fixed loopback HTTP AG-UI task/run stream URL without credentials or query");
  }
  return url;
}

export async function proxyStream(request, response, upstream, origin, fixedGrant) {
  const incoming = new URL(request.url, origin);
  const entries = [...incoming.searchParams];
  if (!upstream) { response.writeHead(404).end(); return; }
  if (request.method !== "GET" || incoming.pathname !== "/observer/stream" || entries.length > 1 || entries.some(([key, value]) => key !== "recovery" || value !== "full") || (request.headers.origin && request.headers.origin !== origin) || request.headers["sec-fetch-site"] === "cross-site") {
    response.writeHead(400).end(); return;
  }
  const authorization = fixedGrant ? `Bearer ${fixedGrant}` : request.headers.authorization;
  const cursor = request.headers["last-event-id"];
  if (typeof authorization !== "string" || !/^Bearer [^\s]+$/.test(authorization) || authorization.length > 16384 || (cursor !== undefined && (typeof cursor !== "string" || cursor.length > 8192 || /[\r\n]/.test(cursor)))) {
    response.writeHead(401).end(); return;
  }
  const target = new URL(upstream);
  if (entries.length) target.searchParams.set("recovery", "full");
  const abort = new AbortController();
  const disconnect = () => abort.abort();
  request.once("aborted", disconnect);
  response.once("close", disconnect);
  try {
    const result = await fetch(target, {
      headers: { Accept: "text/event-stream", Authorization: authorization, ...(cursor ? { "Last-Event-ID": cursor } : {}) },
      signal: abort.signal, redirect: "error", cache: "no-store",
    });
    if (!result.ok || !result.body || !result.headers.get("content-type")?.startsWith("text/event-stream")) {
      await result.body?.cancel();
      response.writeHead(result.ok ? 502 : result.status, { "Cache-Control": "no-store" }).end();
      return;
    }
    response.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-store", "X-Accel-Buffering": "no" });
    response.flushHeaders();
    await pipeline(Readable.fromWeb(result.body), response, { signal: abort.signal });
  } catch {
    if (!response.headersSent && !response.destroyed) response.writeHead(502).end();
    else response.destroy();
  } finally {
    request.off("aborted", disconnect);
    response.off("close", disconnect);
    abort.abort();
  }
}
