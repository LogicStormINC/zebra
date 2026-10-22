import type { BrowserRuntimeDependencies, MountOptions } from "./index.ts";
import { ClientRuntimeError } from "./errors.ts";
import { clientHeaders, readClientJson } from "./runtime_transport.ts";
import { applySurfaceMetadata } from "./surface_metadata.ts";

export const synchronizedMount = (deps: BrowserRuntimeDependencies): boolean => deps.mode === "bff" && deps.surfaceMetadataVersion === 1;

/** One mount waits on existing work only; it never queues new Effect work. */
export async function drainSurfaceWork(jobs: Set<Promise<unknown>>, stopped: () => boolean): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      (async () => { await Promise.resolve(); while (jobs.size && !stopped()) await Promise.allSettled([...jobs]); })(),
      new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new ClientRuntimeError("surface_busy", "surface did not quiesce within5seconds")), 5000); }),
    ]);
  } finally { clearTimeout(timer); }
}

export async function sendRuntimeMount(deps: BrowserRuntimeDependencies, options: MountOptions, revision: number, bindingRevision: number) {
  const body = { client_session_id: deps.clientSessionId, frontend_app_id: options.frontendAppId,
    profile_revision: options.profileRevision, profile_digest: options.profileDigest,
    mounted_readables: options.mountedReadables ?? [], mounted_actions: options.mountedActions,
    ui_revision: revision, mounted_at: new Date().toISOString() };
  const response = await deps.fetchImpl(`${deps.baseUrl}/v1/client-sessions/${deps.clientSessionId}/mount`, {
    method: "POST", headers: clientHeaders(deps), body: JSON.stringify(body),
  });
  if (!response.ok) throw new ClientRuntimeError("mount_rejected", `mount failed with ${response.status}`);
  return synchronizedMount(deps) ? applySurfaceMetadata(await readClientJson(response, 65_536), body,
    { ...deps, controller: deps.mode === "bff" ? deps.controller : false }, bindingRevision) : undefined;
}

export async function releaseRuntimeController(deps: BrowserRuntimeDependencies, coordinates: Record<string, string>): Promise<void> {
  try { await deps.fetchImpl(`${deps.baseUrl}/v1/client-sessions/${deps.clientSessionId}/release`, {
    method: "POST", headers: clientHeaders(deps, true), body: JSON.stringify(coordinates), keepalive: true,
  }); } catch { /* The existing bounded lease is the crash-safe fallback. */ }
}
