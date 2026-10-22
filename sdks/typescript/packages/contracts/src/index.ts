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
  task_id: string;
  run_id: string;
  /** One browser surface only; V1 uses the per-tab Client Session ID. */
  surface_instance_id: string;
  action_name: string;
  arguments: Record<string, unknown>;
  status: ClientEffectStatus;
  expected_ui_revision: number;
  deadline: string;
  expires_at: string;
  idempotency_key: string;
  request_digest: string;
  action_contract_digest: string;
  /** Content-addressed action contract revision. */
  capability_version: string;
  client_binding_digest: string;
}

export interface ReceiptSubmission {
  effect_id: string;
  request_digest: string;
  status: ReceiptTerminalStatus;
  result: Record<string, unknown>;
}

export interface MountedActionDeclaration {
  name: string;
}

export interface RuntimeClientConfig {
  mode?: "legacy";
  /** Zebra base URL reached through the Host BFF proxy. */
  baseUrl: string;
  clientSessionId: string;
  /** Bearer value `"<session-id>:<session-secret>"`; never a HostGrant. */
  sessionCredential: string;
  /** Raw controller fence returned once by the run-binding endpoint. */
  controllerFenceToken?: string;
  /** Controller coordinates returned by the run-binding endpoint. */
  taskId?: string;
  runId?: string;
  runBindingId?: string;
  clientBindingDigest?: string;
  actionContractDigests?: Readonly<Record<string, string>>;
  /** Revision already mounted by a Host BFF before the browser runtime starts. */
  initialUiRevision?: number;
  /** Authenticated AG-UI stream URL for cursor replay. */
  streamUrl?: string;
  /** Defaults to per-tab sessionStorage when the browser permits it. */
  storage?: Storage;
  fetchImpl?: typeof fetch;
}

export const CLIENT_SDK_ERRORS = {
  ACTION_NOT_MOUNTED: "action_not_mounted",
  FENCE_EXPIRED: "fence_expired",
  PROFILE_DIGEST_MISMATCH: "profile_digest_mismatch",
  RECEIPT_CONFLICT: "receipt_conflict",
} as const;

/** Cookie-authenticated same-origin BFF; these identifiers never grant authority. */
export interface BffRuntimeClientConfig extends Omit<RuntimeClientConfig,
  "mode" | "sessionCredential" | "controllerFenceToken" | "streamUrl"> {
  mode: "bff";
  /** Relative fixed surface prefix, e.g. /api/agent/surfaces/binding-id. */
  baseUrl: string;
  /** Display/dispatch hint only; the BFF independently checks native control. */
  controller: boolean;
  /** Explicitly negotiate public native mount facts; no implicit upgrade. */
  surfaceMetadataVersion?: 1;
  /** Explicit native Readable command admission/1; requires synchronized surface. */
  clientStateVersion?: 1;
  /** Durable opaque command markers and receipt-only reconciliation. */
  commandRecoveryVersion?: 1;
  sessionCredential?: never;
  controllerFenceToken?: never;
  streamUrl?: never;
}

export type RuntimeBrowserConfig = RuntimeClientConfig | BffRuntimeClientConfig;
