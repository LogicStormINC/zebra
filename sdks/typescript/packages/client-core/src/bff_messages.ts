/** Explicit original-message recovery; browser storage contains locators, never credentials or text. */
import { ClientRuntimeError } from "./errors.ts";
import { readClientJson } from "./runtime_transport.ts";
export type BFFMessageAnchor = {receipt_key: string; request_hash: string; event_id: string; segment_id: string; segment_sequence: number};
export type BFFMessageState = {version: "1"; status: "clear" | "unknown" | "recorded"; operation: string; revision: number; anchor: BFFMessageAnchor | null};
const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(v) && v !== "00000000-0000-0000-0000-000000000000";
const fail = (): never => {throw new ClientRuntimeError("message_recovery_unavailable", "preserve original message; reconcile without resending");};
function object(v: unknown, keys: string[]): Record<string, unknown> {
  if (!v || typeof v !== "object" || Array.isArray(v) || Object.keys(v).length !== keys.length || keys.some(k => !Object.hasOwn(v, k))) return fail();
  return v as Record<string, unknown>;
}
function validate(value: unknown, operation?: string): BFFMessageState {
  const v = object(value, ["version", "status", "operation", "revision", "anchor"]);
  if (v.version !== "1" || !["clear", "unknown", "recorded"].includes(v.status as string) || !Number.isSafeInteger(v.revision) || Number(v.revision) < 0 || (v.status === "clear" ? v.operation !== "" || operation !== undefined : !uuid(v.operation)) || (operation !== undefined && v.operation !== operation)) return fail();
  if (v.status === "recorded") {
    const a = object(v.anchor, ["receipt_key", "request_hash", "event_id", "segment_id", "segment_sequence"]);
    if (v.revision === 0 || a.receipt_key !== v.operation || typeof a.request_hash !== "string" || !/^[0-9a-f]{64}$/.test(a.request_hash) || !uuid(a.event_id) || !uuid(a.segment_id) || !Number.isSafeInteger(a.segment_sequence) || Number(a.segment_sequence) < 0) return fail();
  } else if (v.anchor !== null) return fail();
  return v as unknown as BFFMessageState;
}
export function createBFFMessages(options: {path: string; storage: Storage; fetch?: typeof fetch}) {
  if (!/^\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_-]+$/.test(options.path) || options.path.length > 512 || !options.storage) return fail();
  const key = `zebra:bff-message:1:${options.path}`, request = options.fetch ?? globalThis.fetch;
  let busy = false;
  function pending(): string | null {
    try { const raw = options.storage.getItem(key); if (raw === null) return null; if (raw.length > 128) return fail();
      const v = object(JSON.parse(raw), ["operation"]); if (!uuid(v.operation)) return fail(); return v.operation;
    } catch {return fail();}
  }
  function save(operation: string | null): void {
    try {if (operation === null) {options.storage.removeItem(key); if (options.storage.getItem(key) !== null) return fail();}
      else {const raw = JSON.stringify({operation}); options.storage.setItem(key, raw); if (options.storage.getItem(key) !== raw) return fail();}
    } catch {return fail();}
  }
  async function read(suffix: string, init: RequestInit, operation?: string): Promise<BFFMessageState> {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await request(options.path + suffix, {...init, mode: "same-origin", credentials: "same-origin", redirect: "error", cache: "no-store", signal: controller.signal, headers: {"X-Overdoze-Message": "1", ...init.headers}});
      if (!response.ok) return fail(); return validate(await readClientJson(response, 4096), operation);
    } catch {return fail();} finally {clearTimeout(timer);}
  }
  function remember(v: BFFMessageState): void {
    const old = pending();
    if (v.operation && old && old !== v.operation) return fail();
    if (v.status === "unknown" && v.operation && !old) save(v.operation);
    if (v.status === "recorded" && old === v.operation) save(null);
  }
  pending();
  return {
    pending,
    async discover(): Promise<BFFMessageState> {
      if (busy) return fail(); busy = true;
      try {const v = await read("", {method: "GET"}); remember(v); return v;} finally {busy = false;}
    },
    async inspect(operation: string): Promise<BFFMessageState> {
      if (!uuid(operation) || busy || (pending() !== null && pending() !== operation)) return fail();
      if (pending() === null) save(operation); busy = true;
      try {const v = await read("/receipt", {method: "GET", headers: {"Idempotency-Key": operation}}, operation); remember(v); return v;} finally {busy = false;}
    },
    async submit(content: string, revision: number): Promise<BFFMessageState> {
      if (busy || pending() !== null || typeof content !== "string" || !content.trim() || !Number.isSafeInteger(revision) || revision < 1 || revision >= 9007199254740990) return fail();
      if (new TextDecoder().decode(new TextEncoder().encode(content)) !== content) return fail();
      const body = JSON.stringify({content, revision}); if (new TextEncoder().encode(body).length > 16000) return fail();
      const operation = globalThis.crypto.randomUUID(); save(operation); busy = true;
      try {const v = await read("", {method: "POST", headers: {"Content-Type": "application/json", "Idempotency-Key": operation}, body}, operation); remember(v); return v;} finally {busy = false;}
    },
  };
}
