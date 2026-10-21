import type { ClientEffectWire } from "@zebra-agent/contracts";
import { ClientRuntimeError } from "./errors.ts";

export function clientHeaders(deps: {
  mode?: "legacy" | "bff" | undefined;
  sessionCredential?: string | undefined;
  controllerFenceToken?: string | undefined;
}, controller = false): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (deps.mode !== "bff") {
    if (deps.sessionCredential !== undefined) headers["X-Zebra-Client-Session"] = deps.sessionCredential;
    if (controller) headers["X-Zebra-Client-Fence"] = deps.controllerFenceToken ?? "";
  }
  return headers;
}

/** Bounded JSON rather than an unbounded response.json() allocation. */
export async function readPendingEffects(response: Response, strict: boolean): Promise<ClientEffectWire[]> {
  const reader = response.body?.getReader();
  if (!reader) throw new ClientRuntimeError("invalid_effects", "missing effect response");
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) break;
      total += chunk.value.byteLength;
      if (total > 1_048_576 || chunks.length >= 4096) throw new ClientRuntimeError("invalid_effects", "effect response exceeds byte budget");
      chunks.push(chunk.value);
    }
  } finally { await reader.cancel(); reader.releaseLock(); }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  const payload: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) throw new ClientRuntimeError("invalid_effects", "invalid effect response");
  const effects = (payload as { effects?: unknown }).effects ?? (strict ? undefined : []);
  if (!Array.isArray(effects) || effects.length > 50 || effects.some(effect => !validEffect(effect, strict))) {
    throw new ClientRuntimeError("invalid_effects", "invalid bounded effect list");
  }
  return effects;
}

function validEffect(value: unknown, strict: boolean): value is ClientEffectWire {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const effect = value as Record<string, unknown>;
  if (strict && ["effect_id", "task_id", "surface_instance_id"].some(key =>
    typeof effect[key] !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(effect[key]))) return false;
  const strings = ["effect_id", "task_id", "run_id", "surface_instance_id", "action_name", "deadline", "expires_at", "idempotency_key", "status"];
  const digests = ["request_digest", "action_contract_digest", "capability_version", "client_binding_digest"];
  return (effect.status === "pending" || effect.status === "delivered") && strings.every(key => typeof effect[key] === "string" && effect[key].length > 0 && effect[key].length <= 256) &&
    digests.every(key => typeof effect[key] === "string" && effect[key].length === 64 && /^[0-9a-f]{64}$/.test(effect[key])) &&
    Number.isSafeInteger(effect.expected_ui_revision) && Number(effect.expected_ui_revision) >= 0 &&
    effect.arguments !== null && typeof effect.arguments === "object" && !Array.isArray(effect.arguments);
}
