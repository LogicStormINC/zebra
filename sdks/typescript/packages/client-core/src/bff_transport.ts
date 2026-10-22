import { ClientRuntimeError } from "./errors.ts";

/** Browser-only locator transport. Actual identity/control live in the business BFF. */
export function createBffFetch(baseUrl: string, sessionId: string, fetchImpl: typeof fetch, commandPath?: string): typeof fetch {
  if (baseUrl.length > 512 || !/^\/[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_-]+)*$/.test(baseUrl)) {
    throw new ClientRuntimeError("invalid_bff_url", "BFF base URL must be a scoped same-origin relative path");
  }
  return async (input, init = {}) => {
    const url = String(input);
    const tail = url.startsWith(baseUrl + "/") ? url.slice(baseUrl.length) : "";
    const method = (init.method ?? "GET").toUpperCase();
    const sessionPrefix = `/v1/client-sessions/${sessionId}/`;
    const allowed = (commandPath !== undefined && ((tail === commandPath && method === "POST") || (tail === commandPath + "/receipt" && method === "GET"))) || (tail === sessionPrefix + "effects" && method === "GET") ||
      (["mount", "heartbeat", "release"].some(action => tail === sessionPrefix + action) && method === "POST") ||
      (/^\/v1\/client-effects\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/receipts$/.test(tail) && method === "POST");
    const headers = new Headers(init.headers);
    if (!allowed || ["authorization", "cookie", "host", "origin", "x-zebra-client-session", "x-zebra-client-fence"].some(name => headers.has(name))) {
      throw new ClientRuntimeError("bff_route_rejected", "BFF request must use the fixed public surface without native credentials");
    }
    if ((method === "GET" && init.body !== undefined) || (method === "POST" &&
      (headers.get("Content-Type") !== "application/json" || typeof init.body !== "string" || new TextEncoder().encode(init.body).byteLength > 65_536))) {
      throw new ClientRuntimeError("bff_body_rejected", "BFF JSON body exceeds the byte budget");
    }
    const deadline = AbortSignal.timeout(5_000);
    return fetchImpl(url, { ...init, headers, credentials: "same-origin", mode: "same-origin",
      redirect: "error", cache: "no-store", signal: init.signal ? AbortSignal.any([init.signal, deadline]) : deadline });
  };
}
