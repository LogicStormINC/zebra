/** Untrusted page snapshots and translation to the published native admission/1. */
import { ClientRuntimeError } from "./errors.ts";
import { readClientJson } from "./runtime_transport.ts";
import { validateSurfaceMetadata, type PublicClientSurfaceMetadata } from "./surface_metadata.ts";

export interface ReadableCommandOptions {
  action: "run" | "resume";
  expectedRevision: number;
  idempotencyKey: string;
  input?: { messages?: unknown[]; resume?: Record<string, unknown> };
}
export interface ReadableCommandResult { status: "accepted"; commandId: string }
export interface ReadableSurface {
  frontendAppId: string;
  clientSessionId: string;
  taskId: string;
  runId: string;
  metadata: PublicClientSurfaceMetadata;
}
function reject(): never { throw new ClientRuntimeError("invalid_readable_command", "invalid bounded Readable command or current surface"); }
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value) || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) return reject();
  if (Object.getOwnPropertySymbols(value).length || typeof (value as Record<string, unknown>).toJSON === "function") return reject();
  return value as Record<string, unknown>;
}
function fields(value: Record<string, unknown>, allowed: string[]) { if (Object.keys(value).some(key => !allowed.includes(key))) reject(); }
function text(value: string) {
  // JSON.stringify silently repairs lone surrogates; native JSONB cannot accept them.
  if (value.includes("\0") || /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value)) reject();
}
/** Copy JSON without coercing Date/undefined/nonfinite values or retaining caller references. */
export function copyReadableJson(value: unknown): Record<string, unknown> {
  object(value); let nodes = 0;
  function visit(item: unknown, depth: number): void {
    if (++nodes > 4096 || depth > 32) reject();
    if (typeof item === "string") text(item);
    else if (typeof item === "number") { if (!Number.isFinite(item)) reject(); }
    else if (item !== null && typeof item === "object") {
      const entries = Array.isArray(item) ? item : Object.values(object(item));
      if (entries.length > 4096 - nodes || Array.isArray(item) && Object.keys(item).length !== item.length) reject();
      for (const key of Object.keys(item)) text(key);
      for (const child of entries) visit(child, depth + 1);
    } else if (item !== null && typeof item !== "boolean") reject();
  }
  visit(value, 0);
  const encoded = JSON.stringify(value);
  if (new TextEncoder().encode(encoded).byteLength > 65536) reject();
  return JSON.parse(encoded);
}
function commandInput(value: unknown, stateAllowed: boolean) {
  const input = object(value ?? {}); fields(input, stateAllowed ? ["messages", "resume", "state"] : ["messages", "resume"]);
  if (input.messages !== undefined && !Array.isArray(input.messages)) reject();
  if (input.resume !== undefined) object(input.resume);
  return input;
}
function envelope(value: Record<string, unknown>) {
  if (!["run", "resume"].includes(String(value.action)) || !Number.isSafeInteger(value.expectedRevision) || Number(value.expectedRevision) < 0) reject();
  const input = commandInput(value.input, true);
  if ((value.action === "run" && input.resume !== undefined) || (value.action === "resume" && input.resume === undefined)) reject();
}
function observation(surface: ReadableSurface) {
  const m = validateSurfaceMetadata(surface.metadata);
  return { uiRevision: m.ui_revision, profileDigest: m.profile_digest,
    mountedSnapshotDigest: m.mounted_snapshot_digest, clientBindingDigest: m.binding_digest };
}
/** Trusted BFF only: caller already checked current business identity, resource, Origin and capability1. */
export function nativeReadableCommand(value: unknown, surface: ReadableSurface) {
  const body = object(value); fields(body, ["action", "expectedRevision", "input", "surface"]); envelope(body);
  const expected = observation(surface), observed = object(body.surface); fields(observed, Object.keys(expected));
  if (Object.entries(expected).some(([key, v]) => observed[key] !== v) ||
    !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(surface.taskId) ||
    !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(surface.clientSessionId) ||
    !surface.frontendAppId || !surface.runId || surface.runId.length > 128 || /[\x00-\x1f/]/.test(surface.runId)) reject();
  const input = commandInput(body.input, true);
  const copied = copyReadableJson({ ...input, messages: input.messages ?? [], state: copyReadableJson(input.state) });
  return { action: body.action, threadId: surface.taskId, runId: surface.runId, expectedRevision: body.expectedRevision,
    input: { ...copied, forwardedProps: { clientStateVersion: 1, frontendAppId: surface.frontendAppId,
      clientSessionId: surface.clientSessionId, ...expected } } };
}

export async function sendReadableCommand(
  request: typeof fetch, baseUrl: string, surface: ReadableSurface,
  options: ReadableCommandOptions, values: Map<string, Record<string, unknown>>, beforeDispatch?: () => void,
): Promise<ReadableCommandResult> {
  const opts = object(options); fields(opts, ["action", "expectedRevision", "idempotencyKey", "input"]); envelope(opts);
  if (typeof opts.idempotencyKey !== "string" || !/^[\x21-\x7e]{1,256}$/.test(opts.idempotencyKey)) reject();
  const input = commandInput(opts.input, false);
  const body = copyReadableJson({ action: options.action, expectedRevision: options.expectedRevision,
    input: { ...input, state: Object.fromEntries(values) }, surface: observation(surface) });
  beforeDispatch?.();
  let response: Response;
  try { response = await request(`${baseUrl}/agui/threads/${surface.taskId}/runs/${encodeURIComponent(surface.runId)}/commands`, {
    method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": options.idempotencyKey }, body: JSON.stringify(body),
  }); } catch { throw new ClientRuntimeError("readable_command_unknown", "Readable command outcome unknown; reconcile at trusted BFF"); }
  if (!response.ok && response.status < 500) throw new ClientRuntimeError("readable_command_rejected", `Readable command rejected (${response.status})`);
  try {
    if (!response.ok) reject();
    const result = object(await readClientJson(response, 4096)); fields(result, ["status", "commandId"]);
    if (result.status !== "accepted" || (typeof result.commandId !== "string" || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(result.commandId))) reject();
    return result as unknown as ReadableCommandResult;
  } catch { throw new ClientRuntimeError("readable_command_unknown", "Readable command outcome unknown; reconcile at trusted BFF"); }
}
