import { ClientRuntimeError } from "./errors.ts";
import type { ClientSurfaceMount } from "./client_surface.ts";

export interface PublicClientSurfaceMetadata {
  client_surface_metadata_contract_version: 1;
  profile_digest: string;
  ui_revision: number;
  mounted_snapshot_digest: string;
  binding_mounted_snapshot_digest: string;
  binding_id: string;
  binding_digest: string;
  binding_revision: number;
  allowed_actions: string[];
  action_contract_digests: Record<string, string>;
  controller: boolean;
}
const fields = ["client_surface_metadata_contract_version", "profile_digest", "ui_revision", "mounted_snapshot_digest",
  "binding_mounted_snapshot_digest", "binding_id", "binding_digest", "binding_revision", "allowed_actions", "action_contract_digests", "controller"];
const digest = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const name = (v: unknown): v is string => typeof v === "string" && v.length <= 64 && /^[a-z][a-z0-9]*(-[a-z0-9]+)*(\.[a-z0-9-]+)+$/.test(v);
function invalid(): never { throw new ClientRuntimeError("invalid_surface_metadata", "invalid public native surface metadata"); }

export function validateSurfaceMetadata(value: unknown): PublicClientSurfaceMetadata {
  if (!value || typeof value !== "object" || Array.isArray(value)) return invalid();
  const v = value as Record<string, unknown>;
  if (Object.keys(v).some(key => !fields.includes(key)) || v.client_surface_metadata_contract_version !== 1 ||
    !digest(v.profile_digest) || !digest(v.mounted_snapshot_digest) || v.binding_mounted_snapshot_digest !== v.mounted_snapshot_digest ||
    !digest(v.binding_digest) || typeof v.binding_id !== "string" || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(v.binding_id) ||
    !Number.isSafeInteger(v.ui_revision) || Number(v.ui_revision) < 0 || !Number.isSafeInteger(v.binding_revision) || Number(v.binding_revision) < 1 ||
    typeof v.controller !== "boolean" || !Array.isArray(v.allowed_actions) || v.allowed_actions.length > 128 ||
    v.allowed_actions.some(a => !name(a)) || new Set(v.allowed_actions).size !== v.allowed_actions.length ||
    !v.action_contract_digests || typeof v.action_contract_digests !== "object" || Array.isArray(v.action_contract_digests)) return invalid();
  const allowed = v.allowed_actions as string[];
  const map = v.action_contract_digests as Record<string, unknown>;
  if (Object.keys(map).length !== v.allowed_actions.length || Object.entries(map).some(([key, hash]) => !allowed.includes(key) || !digest(hash))) return invalid();
  return { ...v, allowed_actions: [...v.allowed_actions], action_contract_digests: { ...map } } as PublicClientSurfaceMetadata;
}

/** Server/BFF only: project exact native facts; never return a credential/fence to the browser. */
export function publicClientSurfaceMetadata(native: unknown): PublicClientSurfaceMetadata {
  if (!native || typeof native !== "object" || Array.isArray(native)) return invalid();
  const input = native as Record<string, unknown>;
  return validateSurfaceMetadata(Object.fromEntries(fields.map(key => [key, input[key]])));
}

export function applySurfaceMetadata(
  value: unknown, mount: ClientSurfaceMount,
  prior: { runBindingId?: string | undefined; controller?: boolean | undefined; clientBindingDigest?: string | undefined; actionContractDigests?: Readonly<Record<string, string>> | undefined },
  bindingRevision: number,
): PublicClientSurfaceMetadata {
  const metadata = validateSurfaceMetadata(value);
  if (metadata.profile_digest !== mount.profile_digest || metadata.ui_revision !== mount.ui_revision ||
    metadata.binding_id !== prior.runBindingId || metadata.controller !== prior.controller || metadata.binding_revision <= bindingRevision ||
    metadata.binding_digest === prior.clientBindingDigest || metadata.allowed_actions.some(a => !mount.mounted_actions.includes(a)) ||
    Object.entries(metadata.action_contract_digests).some(([a, hash]) => prior.actionContractDigests?.[a] !== hash)) return invalid();
  return metadata;
}
