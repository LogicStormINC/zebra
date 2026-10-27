/** Resource-scoped business BFF inbox; never starts a Runtime or resends an original command. */
import { ClientRuntimeError } from "./errors.ts";
import { readClientJson } from "./runtime_transport.ts";
export type UnknownHandling = {revision: number; action: "" | "escalate" | "acknowledge_unknown"; reason: "" | "unobservable" | "support_review"};
export type PendingRequest = {key: string; status: "unknown"; handling: UnknownHandling};
export type PendingRequestsPage = {items: PendingRequest[]; next: string};
const uuid = (s: unknown): s is string => typeof s === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(s) && s !== "00000000-0000-0000-0000-000000000000";
const fail = (): never => {throw new ClientRuntimeError("command_recovery_unavailable", "request discovery unavailable; unknown remains blocking");};
function object(value: unknown, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).length !== keys.length || keys.some(k => !Object.hasOwn(value, k))) return fail();
  return value as Record<string, unknown>;
}
function handling(value: unknown): UnknownHandling {
  const h = object(value, ["revision", "action", "reason"]);
  if (!Number.isSafeInteger(h.revision) || (h.revision as number) < 0 || (h.revision as number) > 32) return fail();
  if (h.revision === 0 ? h.action !== "" || h.reason !== "" : !["escalate", "acknowledge_unknown"].includes(h.action as string) || !["unobservable", "support_review"].includes(h.reason as string)) return fail();
  return h as UnknownHandling;
}
/** Call assertClear before bootstrap/new work on EVERY device. Business BFF must also gate admission.
 * Manual handling retains unknown; no per-tab marker is cleared and no stopped Runtime resumes.
 */
export function createCommandRecoveryInbox(options: {path: string; fetch?: typeof fetch}) {
  if (!options.path.startsWith("/") || options.path.startsWith("//") || options.path.includes("\\") || /[?#\s]/.test(options.path) || options.path.endsWith("/") || options.path.length > 512) return fail();
  const path = options.path; const request = options.fetch ?? globalThis.fetch;
  async function read(suffix: string, init: RequestInit, max: number): Promise<unknown> {
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await request(path + suffix, {...init, credentials: "same-origin", cache: "no-store", redirect: "error", signal: controller.signal});
      if (!response.ok) return fail(); return await readClientJson(response, max);
    } catch {return fail();} finally {clearTimeout(timer);}
  }
  async function discover(after = "", limit = 20): Promise<PendingRequestsPage> {
    if (after !== "" && !uuid(after) || !Number.isInteger(limit) || limit < 1 || limit > 50) return fail();
    const query = new URLSearchParams({limit: String(limit)}); if (after) query.set("after", after);
    const data = object(await read(`?${query}`, {method: "GET"}, 32768), ["items", "next"]);
    if (!Array.isArray(data.items) || data.items.length > limit || typeof data.next !== "string" || data.next !== "" && !uuid(data.next)) return fail();
    const items = data.items.map(v => {
      const p = object(v, ["key", "status", "handling"]); if (!uuid(p.key) || p.status !== "unknown") return fail();
      return {key: p.key, status: "unknown" as const, handling: handling(p.handling)};
    });
    if (items.some((item, i) => item.key <= (i ? items[i - 1]!.key : after)) || data.next !== "" && (items.length !== limit || data.next !== items.at(-1)?.key)) return fail();
    return {items, next: data.next};
  }
  return {
    discover,
    async assertClear(): Promise<void> {
      if ((await discover("", 1)).items.length) throw new ClientRuntimeError("command_recovery_pending", "original unknown requests remain; no resend or new work");
    },
    async reconcile(key: string): Promise<{status: "unknown"} | {status: "accepted"; commandId: string}> {
      if (!uuid(key)) return fail(); const value = await read("/receipt", {method: "GET", headers: {"Idempotency-Key": key}}, 4096);
      if (!value || typeof value !== "object" || Array.isArray(value)) return fail(); const result = value as Record<string, unknown>;
      if (result.status === "unknown" && Object.keys(result).length === 1) return {status: "unknown"};
      object(result, ["status", "commandId"]); if (result.status !== "accepted" || !uuid(result.commandId)) return fail();
      return {status: "accepted", commandId: result.commandId};
    },
    async handle(key: string, input: {revision: number; action: "escalate" | "acknowledge_unknown"; reason: "unobservable" | "support_review"}): Promise<UnknownHandling> {
      if (!uuid(key)) return fail(); const expected = handling({...input, revision: input.revision + 1});
      const value = handling(await read("/handling", {method: "POST", headers: {"Content-Type": "application/json", "Idempotency-Key": key}, body: JSON.stringify(input)}, 4096));
      if (value.revision !== expected.revision || value.action !== expected.action || value.reason !== expected.reason) return fail(); return value;
    },
  };
}
