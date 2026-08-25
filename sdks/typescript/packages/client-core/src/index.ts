/**
 * Zebra client-core: React-free browser runtime (ADR-CLIENT-01).
 *
 * Invariants enforced here: no HostGrant is ever stored; handlers are
 * resolved only through the mounted registry; one effect executes at
 * most once; failed receipts retry; fence expiry stops execution; a
 * profile digest mismatch stops mounting.
 */

import { createHash } from "node:crypto";
import {
  CLIENT_SDK_ERRORS,
  type ClientEffectWire,
  type ReceiptSubmission,
  type RuntimeClientConfig,
} from "../../contracts/src/index.ts";

export type ClientActionHandler = (
  args: Record<string, unknown>,
) => Promise<Record<string, unknown>> | Record<string, unknown>;

export interface MountOptions {
  frontendAppId: string;
  profileDigest: string;
  mountedActions: readonly string[];
  mountedReadables?: readonly string[];
}

export function canonicalDigest(payload: unknown): string {
  const json = JSON.stringify(payload, (_key, value) =>
    value !== null && typeof value === "object" && !Array.isArray(value)
      ? Object.keys(value as Record<string, unknown>)
          .sort()
          .reduce<Record<string, unknown>>((acc, key) => {
            acc[key] = (value as Record<string, unknown>)[key];
            return acc;
          }, {})
      : value,
  );
  return createHash("sha256").update(json).digest("hex");
}

export class ClientRuntimeError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

/** Registry of mounted action handlers; duplicates conflict. */
export class MountedActionRegistry {
  private handlers = new Map<string, ClientActionHandler>();

  mount(name: string, handler: ClientActionHandler): void {
    if (this.handlers.has(name)) {
      throw new ClientRuntimeError(
        "action_already_mounted",
        `action ${name} is already mounted`,
      );
    }
    this.handlers.set(name, handler);
  }

  unmount(name: string): void {
    this.handlers.delete(name);
  }

  names(): string[] {
    return [...this.handlers.keys()];
  }

  has(name: string): boolean {
    return this.handlers.has(name);
  }

  async dispatch(
    name: string,
    args: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const handler = this.handlers.get(name);
    if (handler === undefined) {
      throw new ClientRuntimeError(
        CLIENT_SDK_ERRORS.ACTION_NOT_MOUNTED,
        `action ${name} is not mounted on this page`,
      );
    }
    return handler(args);
  }
}

/** Tracks the mounted UI revision; effects pin the expected revision. */
export class UiRevisionClock {
  private revision = 0;

  get current(): number {
    return this.revision;
  }

  bump(): number {
    this.revision += 1;
    return this.revision;
  }
}

export interface ClientRuntimeDependencies {
  fetchImpl: typeof fetch;
  baseUrl: string;
  clientSessionId: string;
  sessionCredential: string;
}

export class ZebraClientRuntime {
  readonly registry = new MountedActionRegistry();
  readonly uiRevision = new UiRevisionClock();
  private executedEffects = new Set<string>();
  private inflightEffects = new Set<string>();
  private mountedProfileDigest: string | null = null;
  private deps: ClientRuntimeDependencies;
  private stopped = false;

  constructor(deps: ClientRuntimeDependencies) {
    this.deps = deps;
  }

  static fromConfig(config: RuntimeClientConfig): ZebraClientRuntime {
    if (config.sessionCredential.includes(" ")) {
      throw new ClientRuntimeError(
        "invalid_credential",
        "session credential must be '<session-id>:<fence-token>'",
      );
    }
    return new ZebraClientRuntime({
      fetchImpl: config.fetchImpl ?? fetch,
      baseUrl: config.baseUrl,
      clientSessionId: config.clientSessionId,
      sessionCredential: config.sessionCredential,
    });
  }

  /** Mount declares the page's actions; digest drift stops mounting. */
  async mount(options: MountOptions): Promise<void> {
    if (this.stopped) {
      throw new ClientRuntimeError(
        CLIENT_SDK_ERRORS.FENCE_EXPIRED,
        "runtime is stopped",
      );
    }
    if (this.mountedProfileDigest === null) {
      this.mountedProfileDigest = options.profileDigest;
    } else if (this.mountedProfileDigest !== options.profileDigest) {
      throw new ClientRuntimeError(
        CLIENT_SDK_ERRORS.PROFILE_DIGEST_MISMATCH,
        "profile digest changed without a remount",
      );
    }
    this.uiRevision.bump();
    const body = {
      client_session_id: this.deps.clientSessionId,
      frontend_app_id: options.frontendAppId,
      profile_revision: 1,
      profile_digest: options.profileDigest,
      mounted_readables: options.mountedReadables ?? [],
      mounted_actions: options.mountedActions,
      ui_revision: this.uiRevision.current,
      mounted_at: new Date().toISOString(),
    };
    const response = await this.deps.fetchImpl(
      `${this.deps.baseUrl}/v1/client-sessions/${this.deps.clientSessionId}/mount`,
      {
        method: "POST",
        headers: this.headers(),
        body: JSON.stringify(body),
      },
    );
    if (!response.ok) {
      throw new ClientRuntimeError(
        "mount_rejected",
        `mount failed with ${response.status}`,
      );
    }
  }

  /** Reconnect replay of pending effects; each executes at most once. */
  async listPendingEffects(): Promise<ClientEffectWire[]> {
    const response = await this.deps.fetchImpl(
      `${this.deps.baseUrl}/v1/client-sessions/${this.deps.clientSessionId}/effects`,
      { headers: this.headers() },
    );
    if (!response.ok) {
      return [];
    }
    const payload = (await response.json()) as { effects?: ClientEffectWire[] };
    return payload.effects ?? [];
  }

  async runEffect(effect: ClientEffectWire): Promise<void> {
    if (this.stopped) return;
    const effectId = effect.effect_id;
    if (this.executedEffects.has(effectId) || this.inflightEffects.has(effectId)) {
      return; // idempotent local dedup
    }
    this.inflightEffects.add(effectId);
    try {
      const result = await this.registry.dispatch(
        effect.action_name,
        effect.arguments,
      );
      this.executedEffects.add(effectId);
      await this.submitReceipt({
        effect_id: effectId,
        status: "succeeded",
        result,
      });
    } catch (error) {
      this.executedEffects.add(effectId);
      const failure =
        error instanceof ClientRuntimeError &&
        error.code === CLIENT_SDK_ERRORS.ACTION_NOT_MOUNTED
          ? "unavailable"
          : "failed";
      await this.submitReceipt({
        effect_id: effectId,
        status: failure as "unavailable" | "failed",
        result: {
          error: error instanceof Error ? error.message : String(error),
        },
      });
    } finally {
      this.inflightEffects.delete(effectId);
    }
  }

  /** Receipt submission retries until the server accepts it. */
  async submitReceipt(submission: ReceiptSubmission): Promise<boolean> {
    const body = JSON.stringify({
      receipt_id: crypto.randomUUID(),
      effect_id: submission.effect_id,
      idempotency_key: `sdk-receipt:${submission.effect_id}`,
      request_digest: "",
      status: submission.status,
      result: scrubResult(submission.result),
      controller: true,
      received_at: new Date().toISOString(),
    });
    for (let attempt = 0; attempt < 5; attempt += 1) {
      if (this.stopped) return false;
      try {
        const response = await this.deps.fetchImpl(
          `${this.deps.baseUrl}/v1/client-effects/${submission.effect_id}/receipts`,
          {
            method: "POST",
            headers: {
              ...this.headers(),
              "Idempotency-Key": `sdk-receipt:${submission.effect_id}`,
            },
            body,
          },
        );
        if (response.ok) return true;
        if (response.status === 409 || response.status === 410) {
          this.stop(); // stale fence / expired effect: stop executing
          return false;
        }
      } catch {
        // network failure: retry with backoff
      }
      await new Promise((resolve) => setTimeout(resolve, 250 * (attempt + 1)));
    }
    return false;
  }

  stop(): void {
    this.stopped = true;
  }

  get isStopped(): boolean {
    return this.stopped;
  }

  private headers(): Record<string, string> {
    return {
      "Content-Type": "application/json",
      Authorization: `Bearer ${this.deps.clientSessionId}:${fenceOf(this.deps.sessionCredential)}`,
    };
  }
}

function fenceOf(credential: string): string {
  const parts = credential.split(":");
  return parts.length === 2 ? parts[1] : "";
}

/** Receipt results must never carry token/cookie/secret fields. */
export function scrubResult(
  result: Record<string, unknown>,
): Record<string, unknown> {
  const forbidden = ["token", "cookie", "secret", "password", "authorization"];
  const scrubbed: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(result)) {
    if (forbidden.some((token) => key.toLowerCase().includes(token))) {
      scrubbed[key] = "__redacted__";
    } else if (value !== null && typeof value === "object") {
      scrubbed[key] = scrubResult(value as Record<string, unknown>);
    } else {
      scrubbed[key] = value;
    }
  }
  return scrubbed;
}
