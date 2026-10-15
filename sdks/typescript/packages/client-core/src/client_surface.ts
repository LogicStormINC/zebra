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
  if (typeof value.mounted_snapshot_digest !== "string" || !digest.test(value.mounted_snapshot_digest)
    || value.ui_revision !== mount.ui_revision || typeof value.binding_id !== "string" || !uuid.test(value.binding_id)
    || typeof value.binding_digest !== "string" || !digest.test(value.binding_digest)
    || !Number.isSafeInteger(value.binding_revision) || Number(value.binding_revision) < 1
    || value.controller !== binding.controller || !Array.isArray(value.allowed_actions)
    || value.allowed_actions.some(a => typeof a !== "string" || !options.taskCapabilityScope.includes(a) || !mount.mounted_actions.includes(a))
    || (binding.controller ? typeof value.controller_fence_token !== "string" || value.controller_fence_token.length < 16 || /\s/.test(value.controller_fence_token)
      : value.controller_fence_token !== null)) {
    throw new ClientRuntimeError("invalid_client_surface", "invalid client surface response");
  }
  return value as unknown as ClientSurfaceAdmission;
}
