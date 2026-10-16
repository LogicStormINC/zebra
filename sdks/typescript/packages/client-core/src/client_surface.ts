/** Host/BFF transport owns credentials and errors; this helper never stores Grants. */
import { ClientRuntimeError } from "./errors.ts";

export interface ClientSurfaceMount {
  client_session_id: string;
  frontend_app_id: string;
  profile_revision: number;
  profile_digest: string;
  mounted_readables: readonly string[];
  mounted_actions: readonly string[];
  ui_revision: number;
  mounted_at: string;
}
export interface ClientSurfaceAdmission {
  mounted_snapshot_digest: string;
  ui_revision: number;
  binding_id: string;
  binding_digest: string;
  binding_revision: number;
  allowed_actions: string[];
  controller: boolean;
  controller_fence_token: string | null;
}
export interface ClientSurfaceOptions {
  taskId: string;
  runId: string;
  mount: ClientSurfaceMount;
  taskCapabilityScope: readonly string[];
  controller?: boolean;
  capabilities: {client_surface_contract_version?: unknown};
  request: (path: string, body: unknown) => Promise<unknown>;
}

const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const digest = /^[0-9a-f]{64}$/;
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ClientRuntimeError("invalid_client_surface", "invalid client surface response");
  }
  return value as Record<string, unknown>;
}

export async function mountClientSurface(options: ClientSurfaceOptions): Promise<ClientSurfaceAdmission> {
  const {taskId, runId, mount, request} = options;
  if (!uuid.test(taskId) || !uuid.test(mount.client_session_id) || !runId.trim()
    || runId.length > 128 || /[\x00-\x1f/]/.test(runId)) {
    throw new ClientRuntimeError("invalid_client_surface", "invalid client surface target");
  }
  const binding = {task_capability_scope: options.taskCapabilityScope, controller: options.controller ?? true};
  const base = `/v1/tasks/${taskId}/runs/${encodeURIComponent(runId)}`;
  // ponytail: explicit negotiation only; a failed mutation never triggers a fallback or retry.
  const value = options.capabilities.client_surface_contract_version === 1
    ? object(await request(`${base}/client-surface`, {mount, ...binding}))
    : {...object(await request(`/v1/client-sessions/${mount.client_session_id}/mount`, mount)),
      ...object(await request(`${base}/client-bindings`, binding))};
  return validateAdmission(options, value);
}

function validateAdmission(options: ClientSurfaceOptions, value: Record<string, unknown>): ClientSurfaceAdmission {
  const {mount} = options;
  const controller = options.controller ?? true;
  if (typeof value.mounted_snapshot_digest !== "string" || !digest.test(value.mounted_snapshot_digest)
    || value.ui_revision !== mount.ui_revision || typeof value.binding_id !== "string" || !uuid.test(value.binding_id)
    || typeof value.binding_digest !== "string" || !digest.test(value.binding_digest)
    || !Number.isSafeInteger(value.binding_revision) || Number(value.binding_revision) < 1
    || value.controller !== controller || !Array.isArray(value.allowed_actions)
    || value.allowed_actions.some(a => typeof a !== "string" || !options.taskCapabilityScope.includes(a) || !mount.mounted_actions.includes(a))
    || (controller ? typeof value.controller_fence_token !== "string" || value.controller_fence_token.length < 16 || /\s/.test(value.controller_fence_token)
      : value.controller_fence_token !== null)) {
    throw new ClientRuntimeError("invalid_client_surface", "invalid client surface response");
  }
  return value as unknown as ClientSurfaceAdmission;
}


export interface ClientSurfaceOpenOptions extends Omit<ClientSurfaceOptions, "mount" | "request" | "capabilities"> {
  mount: Omit<ClientSurfaceMount, "client_session_id">;
  grant: Record<string, unknown>;
  capabilities: ClientSurfaceOptions["capabilities"] & {client_surface_open_contract_version?: unknown};
  request: (path: string, body: unknown, sessionCredential?: string) => Promise<unknown>;
}
export interface ClientSurfaceOpened extends ClientSurfaceAdmission {
  client_session_id: string;
  session_credential: string;
}

/** Host/BFF only: request supplies fresh Host authority; never cache the returned credential. */
export async function openClientSurface(options: ClientSurfaceOpenOptions): Promise<ClientSurfaceOpened> {
  const {taskId, runId, request} = options;
  if (!uuid.test(taskId) || !runId.trim() || runId.length > 128 || /[\x00-\x1f/]/.test(runId)
    || "client_session_id" in options.mount) {
    throw new ClientRuntimeError("invalid_client_surface", "invalid client surface target");
  }
  const combined = options.capabilities.client_surface_open_contract_version === 1;
  // ponytail: negotiate before mutation. A timeout/invalid response never retries or falls back.
  const opened = object(await request(combined
    ? `/v1/tasks/${taskId}/runs/${encodeURIComponent(runId)}/client-surface` : "/v1/client-sessions",
    combined ? {grant: options.grant, mount: options.mount,
      task_capability_scope: options.taskCapabilityScope, controller: options.controller ?? true}
      : {grant: options.grant}));
  const session = opened.client_session_id;
  const credential = opened.session_credential;
  if (typeof session !== "string" || !uuid.test(session) || typeof credential !== "string"
    || !credential.startsWith(`${session}:`) || credential.length <= session.length + 16 || /\s/.test(credential)) {
    throw new ClientRuntimeError("invalid_client_surface", "invalid client session response");
  }
  const mounted = {...options, mount: {...options.mount, client_session_id: session},
    request: (path: string, body: unknown) => request(path, body, credential)};
  const admission = combined ? validateAdmission(mounted, opened) : await mountClientSurface(mounted);
  return {...admission, client_session_id: session, session_credential: credential};
}
