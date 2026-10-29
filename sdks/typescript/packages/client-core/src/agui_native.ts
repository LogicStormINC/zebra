/** Server-only native rail. A business BFF owns these coordinates and fresh headers. */
import type { RunAgentInput } from "@ag-ui/core";
import type { AgUiAdmissionResult } from "./agui_http.js";
import { readClientJson } from "./runtime_transport.js";

export function createNativeAgUiTransport(options: {
  origin: string;
  publicPath: string;
  taskId: string;
  internalRunId: string;
  segmentId: string;
  expectedRevision: number;
  /** Original trusted BFF locator, including atomic initial RUN's returned Event key. */
  originalOperation?: string;
  originalEventKey?: string;
  profile: "agui-standard-1.0" | "zebra-reliable-v2-agui-1.0";
  revision?: 1 | 2;
  /** Revision-two native response. Results are captured only with the FIRST receipt. */
  interaction?: {
    effectId?: string;
    previousNativeRunId?: string;
    receipt?: Record<string, unknown>;
  };
  /** Fresh authenticated Host/Client credentials; Controller fence only on native writes. */
  headers: (write: boolean) => Promise<Record<string, string>>;
  fetch?: typeof fetch;
}) {
  if (typeof window !== "undefined") throw new Error("Native AG-UI coordinates are server-only");
  const origin = new URL(options.origin);
  if (origin.origin !== options.origin || origin.username || origin.password ||
      (origin.protocol !== "https:" && !(origin.protocol === "http:" && ["127.0.0.1", "localhost"].includes(origin.hostname)))) {
    throw new Error("Native AG-UI origin must be an exact trusted origin");
  }
  if (!/^\/[A-Za-z0-9_/-]+$/.test(options.publicPath)) throw new Error("A fixed BFF path is required");
  const nativeOrigin = origin.origin, publicPath = options.publicPath, profile = options.profile;
  let observedEventKey = options.originalEventKey;
  const segmentId = options.segmentId, revision = options.revision;
  const interaction = options.interaction ? structuredClone(options.interaction) : undefined;
  if (interaction && revision !== 2) throw new Error("Native interactions require explicit revision 2");
  const expectedRevision = options.expectedRevision, taskId = options.taskId, internalRunId = options.internalRunId;
  const freshHeaders = options.headers;
  const path = `/agui/threads/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(internalRunId)}`;
  const fetchImpl = options.fetch ?? globalThis.fetch;
  let operation: string | undefined = options.originalOperation;
  let dispatched = false;
  async function headers(write: boolean, observation = false): Promise<Headers> {
    const value = new Headers(await freshHeaders(write));
    value.set("X-Zebra-Command-Segment", segmentId);
    value.set("Idempotency-Key", observation ? observedEventKey ?? operation! : interaction ? operation! : observedEventKey ?? operation!);
    value.set("X-Zebra-AGUI-Profile", profile);
    if (write && interaction?.previousNativeRunId) {
      if (!value.get("X-Zebra-Previous-Host-Grant")?.startsWith("Bearer ")) {
        throw new Error("A fresh separate previous native Host Grant is required");
      }
    } else value.delete("X-Zebra-Previous-Host-Grant");
    if (revision !== undefined) value.set("X-Zebra-AGUI-Revision", String(revision));
    if (interaction?.effectId) value.set("X-Zebra-Effect-Id", interaction.effectId);
    value.set("Accept", "text/event-stream");
    return value;
  }
  async function request(suffix: string, write: boolean, body?: unknown): Promise<AgUiAdmissionResult> {
    const nativeHeaders = await headers(write);
    nativeHeaders.set("Content-Type", "application/json");
    const response = await fetchImpl(nativeOrigin + path + suffix, { method: write ? "POST" : "GET",
      headers: nativeHeaders, ...(write ? { body: JSON.stringify(body) } : {}), signal: AbortSignal.timeout(5_000), redirect: "error", cache: "no-store" });
    if (!response.ok) throw new Error(`Native AG-UI admission unavailable (${response.status})`);
    const raw = await readClientJson(response, 1_048_576);
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("Invalid native admission response");
    const value = raw as Record<string, unknown>;
    if (value.status === "binding_pending" || interaction && value.status === "not_observed") return { operation: operation!, pending: true };
    if (value.status !== "prepared" || !value.input || typeof value.input !== "object") {
      throw new Error("Native AG-UI operation has no prepared public successor");
    }
    if (interaction) {
      if (typeof value.sourceKey !== "string" || !/^[\x21-\x7e]{1,256}$/.test(value.sourceKey)) {
        throw new Error("Native interaction receipt omits its exact source coordinate");
      }
      observedEventKey = value.sourceKey;
    }
    return { operation: operation!, input: structuredClone(value.input as RunAgentInput) };
  }
  return {
    reliable: profile === "zebra-reliable-v2-agui-1.0",
    async admit(captured: string, input: RunAgentInput): Promise<AgUiAdmissionResult> {
      if (dispatched || operation || input.threadId !== taskId || (interaction ? !/^agui:[0-9a-f]{64}$/.test(input.runId) : input.runId !== internalRunId)) {
        throw new Error("Native intent must be captured once for its exact server target");
      }
      operation = captured; dispatched = true;
      return request(interaction ? "/interaction" : "/prepare", true, {
        expectedRevision, input,
        ...(interaction?.previousNativeRunId ? {previousNativeRunId:interaction.previousNativeRunId} : {}),
        ...(interaction?.receipt ? {receipt:{...interaction.receipt,receipt_id:captured}} : {}),
      });
    },
    async receipt(captured: string): Promise<AgUiAdmissionResult> {
      if (operation && captured !== operation) throw new Error("Reconcile the original native operation");
      operation = captured;
      return request(interaction ? "/interaction" : "/prepared", false);
    },
    fetch: (async (url, init = {}) => {
      if (String(url) !== publicPath || !operation) throw new Error("Observe only the original BFF operation locator");
      const current = await request(interaction ? "/interaction" : "/prepared", false);
      if ("pending" in current) throw new Error("Original native binding is not ready");
      const nativeHeaders = await headers(false, true);
      nativeHeaders.set("Content-Type", "application/json");
      if (profile === "zebra-reliable-v2-agui-1.0") {
        const cursor = new Headers(init.headers).get("Last-Event-ID");
        if (cursor) nativeHeaders.set("Last-Event-ID", cursor);
        return fetchImpl(nativeOrigin + path + "/stream", { method: "GET", headers: nativeHeaders,
          ...(init.signal ? { signal: init.signal } : {}), redirect: "error", cache: "no-store" });
      }
      // Official HttpAgent creates this JSON; the native endpoint verifies every
      // field against its immutable accepted Event and exact public binding.
      return fetchImpl(nativeOrigin + path + "/stream", { method: "POST", body: init.body ?? null,
        headers: nativeHeaders, ...(init.signal ? { signal: init.signal } : {}), redirect: "error", cache: "no-store" });
    }) as typeof fetch,
  };
}
