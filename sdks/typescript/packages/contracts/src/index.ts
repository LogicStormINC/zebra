/** Wire contracts shared by the Zebra TypeScript SDK (ADR-CLIENT-01). */

export type ClientEffectStatus =
  | "pending"
  | "delivered"
  | "succeeded"
  | "failed"
  | "declined"
  | "unavailable"
  | "stale_ui_state"
  | "expired"
  | "uncertain"
  | "cancelled";

/** Receipt statuses a browser controller may submit. */
export type ReceiptTerminalStatus =
  | "succeeded"
  | "failed"
  | "declined"
  | "unavailable"
  | "stale_ui_state";

export interface ClientEffectWire {
  effect_id: string;
  action_name: string;
  arguments: Record<string, unknown>;
  status: ClientEffectStatus;
  expected_ui_revision: number;
  expires_at: string;
  request_digest: string;
}

export interface ReceiptSubmission {
  effect_id: string;
  status: ReceiptTerminalStatus;
  result: Record<string, unknown>;
}

export interface MountedActionDeclaration {
  name: string;
}

export interface RuntimeClientConfig {
  /** Zebra base URL reached through the Host BFF proxy. */
  baseUrl: string;
  clientSessionId: string;
  /** Bearer value `"<session-id>:<fence-token>"`; never a HostGrant. */
  sessionCredential: string;
  fetchImpl?: typeof fetch;
}

export const CLIENT_SDK_ERRORS = {
  ACTION_NOT_MOUNTED: "action_not_mounted",
  FENCE_EXPIRED: "fence_expired",
  PROFILE_DIGEST_MISMATCH: "profile_digest_mismatch",
  RECEIPT_CONFLICT: "receipt_conflict",
} as const;
