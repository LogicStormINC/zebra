/** Explicit Surface intent and mapping recovery. Never submits RUN or claims Controller. */
import {ClientRuntimeError} from "./errors.ts";
import {readClientJson} from "./runtime_transport.ts";
import {validateSurfaceMetadata, type PublicClientSurfaceMetadata} from "./surface_metadata.ts";
export type BFFSurfaceBinding = {mappingRevision: number; taskId: string; runId: string; clientSessionId: string};
export type BFFSurfaceState = {version: "1"; status: "clear" | "unknown" | "recorded" | "rejected" | "installed"; operation: string; revision: number; surface: PublicClientSurfaceMetadata | null; binding: BFFSurfaceBinding | null};
type Pending = {operation: string; stage: "surface" | "recorded"} | {operation: string; stage: "install"; revision: number};
const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(v) && v !== "00000000-0000-0000-0000-000000000000";
const revision = (v: unknown, min = 0): v is number => Number.isSafeInteger(v) && Number(v) >= min;
const fail = (): never => {throw new ClientRuntimeError("surface_recovery_unavailable", "preserve original Surface intent; observe without resending");};
function object(v: unknown, keys: string[]): Record<string, unknown> {
 if (!v || typeof v !== "object" || Array.isArray(v) || Object.keys(v).length !== keys.length || keys.some(k => !Object.hasOwn(v, k))) return fail();
 return v as Record<string, unknown>;
}
function validate(value: unknown, operation?: string): BFFSurfaceState {
 const v = object(value, ["version", "status", "operation", "revision", "surface", "binding"]);
 if (v.version !== "1" || !["clear", "unknown", "recorded", "rejected", "installed"].includes(v.status as string) || !revision(v.revision) || (v.status === "clear" ? v.operation !== "" || operation !== undefined : !uuid(v.operation)) || (operation !== undefined && operation !== v.operation)) return fail();
 if (v.status === "recorded" || v.status === "installed") {
  if (!revision(v.revision, 1)) return fail();
  const m = validateSurfaceMetadata(v.surface); if (!m.controller || !uuid(m.binding_id)) return fail(); v.surface = m;
 } else if (v.surface !== null) return fail();
 if (v.status === "installed") {
  const b = object(v.binding, ["mappingRevision", "taskId", "runId", "clientSessionId"]);
  if (!revision(b.mappingRevision, 1) || !uuid(b.taskId) || !uuid(b.runId) || !uuid(b.clientSessionId)) return fail();
 } else if (v.binding !== null) return fail();
 if (v.status === "rejected" && !revision(v.revision, 1)) return fail();
 return v as unknown as BFFSurfaceState;
}
function names(value: unknown): string[] {
 if (!Array.isArray(value) || value.length > 128 || value.some(v => typeof v !== "string" || v.length > 64 || !/^[a-z][a-z0-9]*(-[a-z0-9]+)*(\.[a-z0-9-]+)+$/.test(v)) || new Set(value).size !== value.length) return fail();
 return [...value].sort() as string[];
}
export function createBFFSurface(options: {path: string; storage: Storage; fetch?: typeof fetch}) {
 if (!/^\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_-]+$/.test(options.path) || options.path.length > 512 || !options.storage) return fail();
 const key = `zebra:bff-surface:1:${options.path}`, request = options.fetch ?? globalThis.fetch;
 let busy = false;
 function pending(): Pending | null {
  try {const raw = options.storage.getItem(key); if (raw === null) return null; if (raw.length > 256) return fail();
   const v = JSON.parse(raw); object(v, v?.stage === "install" ? ["operation", "stage", "revision"] : ["operation", "stage"]);
   if (!uuid(v.operation) || !["surface", "recorded", "install"].includes(v.stage) || v.stage === "install" && (!revision(v.revision) || v.revision >= 9007199254740990)) return fail(); return v;
  } catch {return fail();}
 }
 function save(value: Pending | null): void {
  try {if (value === null) {options.storage.removeItem(key); if (options.storage.getItem(key) !== null) return fail();}
   else {const raw = JSON.stringify(value); options.storage.setItem(key, raw); if (options.storage.getItem(key) !== raw) return fail();}
  } catch {return fail();}
 }
 async function read(suffix: string, init: RequestInit, operation?: string): Promise<BFFSurfaceState> {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 10000);
  try {const response = await request(options.path + suffix, {...init, mode: "same-origin", credentials: "same-origin", redirect: "error", cache: "no-store", signal: controller.signal, headers: {"X-Overdoze-Surface": "1", ...init.headers}});
   if (!response.ok) return fail(); return validate(await readClientJson(response, 65536), operation);
  } catch {return fail();} finally {clearTimeout(timer);}
 }
 function remember(v: BFFSurfaceState, installed = false): BFFSurfaceState {
  const old = pending();
  if (v.operation && old && v.operation !== old.operation) return fail();
  if (v.status === "installed") {
   if (!installed || !old || old.stage === "surface" || old.stage === "install" && v.binding!.mappingRevision !== old.revision + 1) return fail(); save(null);
  } else if (v.operation && !old) save({operation: v.operation, stage: v.status === "recorded" ? "recorded" : "surface"});
  else if (v.status === "recorded" && old?.stage === "surface") save({operation: v.operation, stage: "recorded"});
  return v;
 }
 async function observe(): Promise<BFFSurfaceState> {
  const old = pending(); if (busy || !old || old.stage === "surface") return fail(); busy = true;
  try {return remember(await read("/installed", {method: "GET", headers: {"Idempotency-Key": old.operation}}, old.operation), true);} finally {busy = false;}
 }
 pending();
 return {
  pending,
  observe,
  async discover(): Promise<BFFSurfaceState> {
   if (busy) return fail(); busy = true;
   try {return remember(await read("", {method: "GET"}));} finally {busy = false;}
  },
  async inspect(operation?: string): Promise<BFFSurfaceState> {
   const old = pending(), op = operation ?? old?.operation;
   if (!uuid(op) || busy || old && old.operation !== op) return fail();
   if (old?.stage === "install") return observe();
   if (!old) save({operation: op, stage: "surface"}); busy = true;
   try {return remember(await read("/receipt", {method: "GET", headers: {"Idempotency-Key": op}}, op));} finally {busy = false;}
  },
  async submit(captured: {mountedActions: string[]; mountedReadables: string[]; input?: unknown}, expected: number): Promise<BFFSurfaceState> {
   if (busy || pending() || (!revision(expected, 1) || expected >= 9007199254740990) || !captured || typeof captured !== "object" || Object.keys(captured).some(k => !["mountedActions", "mountedReadables", "input"].includes(k))) return fail();
   const body = JSON.stringify({revision: expected, prepared: {mountedActions: names(captured.mountedActions), mountedReadables: names(captured.mountedReadables)}});
   if (new TextEncoder().encode(body).length > 16000) return fail();
   const operation = globalThis.crypto.randomUUID(); save({operation, stage: "surface"}); busy = true;
   try {return remember(await read("", {method: "POST", headers: {"Content-Type": "application/json", "Idempotency-Key": operation}, body}, operation));} finally {busy = false;}
  },
  async install(expected: number): Promise<BFFSurfaceState> {
   const old = pending(); if (busy || old?.stage !== "recorded" || (!revision(expected) || expected >= 9007199254740990)) return fail();
   save({operation: old.operation, stage: "install", revision: expected}); busy = true;
   try {return remember(await read("/install", {method: "POST", headers: {"Content-Type": "application/json", "Idempotency-Key": old.operation}, body: JSON.stringify({revision: expected})}, old.operation), true);} finally {busy = false;}
  },
 };
}
