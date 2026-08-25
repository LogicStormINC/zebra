import type { ReceiptSubmission } from "../../contracts/src/index.ts";

export interface ClientRuntimeState {
  executedEffects: Set<string>;
  inflightEffects: Set<string>;
  pendingReceipts: Map<string, ReceiptSubmission>;
}

/** Per-tab refresh recovery; browsers provide sessionStorage for this boundary. */
export class ClientRuntimeStateStore {
  private readonly key: string;
  private readonly storage: Storage | undefined;

  constructor(storage: Storage | undefined, clientSessionId: string) {
    this.storage = storage;
    this.key = `zebra:client-runtime:${clientSessionId}`;
  }

  load(): ClientRuntimeState {
    try {
      const raw = this.storage?.getItem(this.key);
      if (raw === undefined || raw === null) return emptyState();
      const parsed = JSON.parse(raw) as {
        executedEffects?: unknown;
        inflightEffects?: unknown;
        pendingReceipts?: unknown;
      };
      const executedEffects = Array.isArray(parsed.executedEffects)
        ? new Set(parsed.executedEffects.filter(isText))
        : new Set<string>();
      const inflightEffects = Array.isArray(parsed.inflightEffects)
        ? new Set(parsed.inflightEffects.filter(isText))
        : new Set<string>();
      const pendingReceipts = new Map<string, ReceiptSubmission>();
      if (Array.isArray(parsed.pendingReceipts)) {
        for (const item of parsed.pendingReceipts) {
          if (isReceipt(item)) pendingReceipts.set(item.effect_id, item);
        }
      }
      return { executedEffects, inflightEffects, pendingReceipts };
    } catch {
      return emptyState();
    }
  }

  save(state: ClientRuntimeState): void {
    try {
      this.storage?.setItem(this.key, JSON.stringify({
        executedEffects: [...state.executedEffects].slice(-500),
        inflightEffects: [...state.inflightEffects].slice(-100),
        pendingReceipts: [...state.pendingReceipts.values()].slice(-100),
      }));
    } catch {
      // Storage denial/quota exhaustion degrades to the in-memory contract.
    }
  }
}

function emptyState(): ClientRuntimeState {
  return {
    executedEffects: new Set(),
    inflightEffects: new Set(),
    pendingReceipts: new Map(),
  };
}

function isText(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 256;
}

function isReceipt(value: unknown): value is ReceiptSubmission {
  if (value === null || typeof value !== "object") return false;
  const receipt = value as Partial<ReceiptSubmission>;
  return (
    isText(receipt.effect_id) &&
    typeof receipt.request_digest === "string" &&
    /^[0-9a-f]{64}$/.test(receipt.request_digest) &&
    (receipt.status === "succeeded" ||
      receipt.status === "failed" ||
      receipt.status === "declined" ||
      receipt.status === "unavailable" ||
      receipt.status === "stale_ui_state") &&
    receipt.result !== null &&
    typeof receipt.result === "object" &&
    !Array.isArray(receipt.result)
  );
}
