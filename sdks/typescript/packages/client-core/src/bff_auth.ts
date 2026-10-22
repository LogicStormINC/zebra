/** Same-origin business authentication. Platform credentials never enter this API or storage. */
import { ClientRuntimeError } from "./errors.ts";
import { readClientJson } from "./runtime_transport.ts";
export type BFFAuthState = {
  version: "1"; status: "active" | "refresh_required" | "unknown" | "closed"; revision: number; currentOperation: string;
  receipt: {operation: string; kind: "install" | "refresh" | "retire" | ""; outcome: "completed" | "unknown" | "not_observed"};
};
const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value) && value !== "00000000-0000-0000-0000-000000000000";
const fail = (): never => {throw new ClientRuntimeError("auth_unavailable", "authentication unavailable; reconcile original operation without retry");};
const blocked = (): never => {throw new ClientRuntimeError("auth_pending", "authentication pending or closed; no bootstrap or automatic refresh");};
function object(value: unknown, names: string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).length !== names.length || names.some(k => !Object.hasOwn(value, k))) return fail();
  return value as Record<string, unknown>;
}
function state(value: unknown, operation?: string): BFFAuthState {
  const s = object(value, ["version", "status", "revision", "currentOperation", "receipt"]);
  const r = object(s.receipt, ["operation", "kind", "outcome"]);
  if (s.version !== "1" || !["active", "refresh_required", "unknown", "closed"].includes(s.status as string) || !Number.isSafeInteger(s.revision) || (s.revision as number) < 1 || !uuid(s.currentOperation) || !uuid(r.operation) || (operation !== undefined && r.operation !== operation)) return fail();
  if (!["completed", "unknown", "not_observed"].includes(r.outcome as string) || (r.outcome === "not_observed" ? r.kind !== "" : !["install", "refresh", "retire"].includes(r.kind as string))) return fail();
  if (operation === undefined && (r.operation !== s.currentOperation || r.outcome === "not_observed" || (s.status === "unknown" ? r.outcome !== "unknown" : r.outcome !== "completed"))) return fail();
  return s as unknown as BFFAuthState;
}
type Marker = {operation: string; kind: "refresh" | "retire"};
/** Construct per business login context with stable same-origin path and sessionStorage.
 * Call assertActive before starting a fresh Runtime. BFF admission must independently use
 * bffsessions.Service.Access; this browser check is UX, never an authorization boundary.
 */
export function createBFFAuth(options: {path: string; storage: Storage; fetch?: typeof fetch}) {
  if (!/^\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_-]+$/.test(options.path) || options.path.length > 512 || !options.storage) return fail();
  const key = `zebra:bff-auth:1:${options.path}`;
  const request = options.fetch ?? globalThis.fetch;
  let busy = false;
  function pending(): Marker | null {
    try {
      const raw = options.storage.getItem(key); if (raw === null) return null; if (raw.length > 160) return fail();
      const m = object(JSON.parse(raw), ["operation", "kind"]);
      if (!uuid(m.operation) || !["refresh", "retire"].includes(m.kind as string)) return fail(); return m as Marker;
    } catch {return fail();}
  }
  function persist(marker: Marker | null): void {
    try {
      if (marker === null) { options.storage.removeItem(key); if (options.storage.getItem(key) !== null) fail(); }
      else { const raw = JSON.stringify(marker); options.storage.setItem(key, raw); if (options.storage.getItem(key) !== raw) fail(); }
    } catch {return fail();}
  }
  async function read(suffix: string, init: RequestInit, operation?: string): Promise<BFFAuthState> {
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await request(options.path + suffix, {...init, credentials: "same-origin", cache: "no-store", redirect: "error", signal: controller.signal, headers: {"X-Overdoze-Auth": "1", ...init.headers}});
      if (!response.ok) return fail(); return state(await readClientJson(response, 4096), operation);
    } catch {return fail();} finally {clearTimeout(timer);}
  }
  async function inspect(operation: string): Promise<BFFAuthState> {
    if (!uuid(operation) || busy) return fail();
    busy = true;
    try {
      const result = await read("/receipt", {method: "GET", headers: {"Idempotency-Key": operation}}, operation);
      const m = pending();
      if (m?.operation === operation && result.receipt.outcome === "completed") {
        if (m.kind !== result.receipt.kind) return fail(); persist(null);
      }
      return result;
    } finally {busy = false;}
  }
  async function mutate(kind: "refresh" | "retire", revision: number): Promise<BFFAuthState> {
    if (busy || !Number.isSafeInteger(revision) || revision < 1 || revision > 9007199254740989) return fail();
    const previous = pending(); if (kind === "refresh" && previous !== null) return blocked();
    // Explicit retirement may replace a local unresolved locator. Original unknown stays in BFF audit;
    // it is never marked completed or replayed. A confirmed closed family needs fresh business login.
    const marker: Marker = {operation: globalThis.crypto.randomUUID(), kind};
    persist(marker); busy = true;
    try {
      const result = await read(`/${kind}`, {method: "POST", headers: {"Content-Type": "application/json", "Idempotency-Key": marker.operation}, body: JSON.stringify({revision})}, marker.operation);
      if (result.receipt.kind !== kind) return fail();
      if (result.receipt.outcome === "completed") persist(null);
      return result;
    } finally {busy = false;}
  }
  pending();
  return {
    pending,
    state: async () => read("", {method: "GET"}),
    inspect,
    refresh: (revision: number) => mutate("refresh", revision),
    retire: (revision: number) => mutate("retire", revision),
    async assertActive(): Promise<BFFAuthState> {
      if (pending() !== null || busy) return blocked();
      const result = await read("", {method: "GET"});
      if (pending() !== null || busy || result.status !== "active") return blocked(); return result;
    },
  };
}
