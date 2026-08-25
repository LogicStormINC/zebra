/**
 * Zebra client-core: React-free browser runtime (ADR-CLIENT-01).
 *
 * Invariants enforced here: no HostGrant is ever stored; handlers are
 * resolved only through the mounted registry; one effect executes at
 * most once; failed receipts retry; fence expiry stops execution; a
 * profile digest mismatch stops mounting.
 */
import {
  CLIENT_SDK_ERRORS,
  type ClientEffectWire,
  type ReceiptSubmission,
  type RuntimeClientConfig,
} from "../../contracts/src/index.ts";
import { ClientRuntimeStateStore } from "./runtime_state.ts";
import { consumeClientEffectStream } from "./sse_stream.ts";
import { normalizeReceipt, submitClientReceipt } from "./receipt_transport.ts";
import { MountedActionRegistry } from "./action_registry.ts";
import { ClientRuntimeError } from "./errors.ts";
export { scrubResult } from "./result_security.ts";
export { canonicalDigest } from "./canonical_digest.ts";
export { MountedActionRegistry, type ClientActionHandler } from "./action_registry.ts";
export { ClientRuntimeError } from "./errors.ts";
export interface MountOptions {
  frontendAppId: string;
  profileRevision: number;
  profileDigest: string;
  mountedActions: readonly string[];
  mountedReadables?: readonly string[];
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
  controllerFenceToken?: string | undefined;
  taskId?: string | undefined;
  runId?: string | undefined;
  runBindingId?: string | undefined;
  clientBindingDigest?: string | undefined;
  actionContractDigests?: Readonly<Record<string, string>> | undefined;
  streamUrl?: string | undefined;
  storage?: Storage | undefined;
}

export class ZebraClientRuntime {
  readonly registry = new MountedActionRegistry();
  readonly readableNames = new Set<string>();
  readonly uiRevision = new UiRevisionClock();
  private executedEffects: Set<string>;
  private inflightEffects: Set<string>;
  private pendingReceipts: Map<string, ReceiptSubmission>;
  private stateStore: ClientRuntimeStateStore;
  private mountedProfileDigest: string | null = null;
  private abortController: AbortController | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private queuedMount: MountOptions | null = null;
  private mountFlush: Promise<void> | null = null;
  private deps: ClientRuntimeDependencies;
  private stopped = false;

  constructor(deps: ClientRuntimeDependencies) {
    this.deps = deps;
    this.stateStore = new ClientRuntimeStateStore(deps.storage, deps.clientSessionId);
    const restored = this.stateStore.load();
    this.executedEffects = restored.executedEffects;
    this.inflightEffects = restored.inflightEffects;
    this.pendingReceipts = restored.pendingReceipts;
  }

  static fromConfig(config: RuntimeClientConfig): ZebraClientRuntime {
    const sessionSecret = config.sessionCredential.slice(config.clientSessionId.length + 1);
    if (
      !config.sessionCredential.startsWith(`${config.clientSessionId}:`) ||
      sessionSecret.length < 16 ||
      /\s/.test(sessionSecret)
    ) {
      throw new ClientRuntimeError(
        "invalid_credential",
        "session credential must be '<session-id>:<session-secret>'",
      );
    }
    const controllerCoordinates = [
      config.taskId,
      config.runId,
      config.runBindingId,
      config.clientBindingDigest,
      config.actionContractDigests,
    ];
    if (
      config.controllerFenceToken !== undefined &&
      (
        config.controllerFenceToken.length < 16 ||
        /\s/.test(config.controllerFenceToken) ||
        controllerCoordinates.some(
          (value) =>
            value === undefined ||
            (typeof value === "string" && value.trim() === ""),
        ) ||
        !/^[0-9a-f]{64}$/.test(config.clientBindingDigest ?? "") ||
        Object.values(config.actionContractDigests ?? {}).some(
          (digest) => !/^[0-9a-f]{64}$/.test(digest),
        )
      )
    ) {
      throw new ClientRuntimeError(
        "invalid_controller_binding",
        "controller fence requires binding coordinates and action digests",
      );
    }
    if (
      config.streamUrl !== undefined &&
      new URL(config.streamUrl, config.baseUrl).origin !== new URL(config.baseUrl).origin
    ) {
      throw new ClientRuntimeError(
        "cross_origin_stream",
        "the AG-UI stream must share the Host BFF origin",
      );
    }
    return new ZebraClientRuntime({
      fetchImpl: config.fetchImpl ?? fetch,
      baseUrl: config.baseUrl,
      clientSessionId: config.clientSessionId,
      sessionCredential: config.sessionCredential,
      controllerFenceToken: config.controllerFenceToken,
      taskId: config.taskId,
      runId: config.runId,
      runBindingId: config.runBindingId,
      clientBindingDigest: config.clientBindingDigest,
      actionContractDigests: config.actionContractDigests,
      streamUrl: config.streamUrl,
      storage: config.storage ?? browserSessionStorage(),
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
      profile_revision: options.profileRevision,
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

  /** Coalesce one React commit into one initial/narrowing mount snapshot. */
  scheduleMount(options: MountOptions): Promise<void> {
    if (this.stopped) return Promise.resolve();
    this.queuedMount = options;
    this.mountFlush ??= Promise.resolve().then(async () => {
      try {
        while (this.queuedMount !== null) {
          if (this.stopped) {
            this.queuedMount = null;
            return;
          }
          const next = this.queuedMount;
          this.queuedMount = null;
          await this.mount(next);
        }
      } finally {
        this.mountFlush = null;
      }
    });
    return this.mountFlush;
  }

  mountReadable(name: string): void {
    this.readableNames.add(name);
  }

  unmountReadable(name: string): void {
    this.readableNames.delete(name);
  }

  /** Reconnect replay of pending effects; each executes at most once. */
  async listPendingEffects(): Promise<ClientEffectWire[]> {
    try {
      const response = await this.deps.fetchImpl(
        `${this.deps.baseUrl}/v1/client-sessions/${this.deps.clientSessionId}/effects`,
        { headers: this.headers() },
      );
      if (!response.ok) return [];
      const payload = (await response.json()) as { effects?: ClientEffectWire[] };
      return payload.effects ?? [];
    } catch {
      return [];
    }
  }

  /** Start durable replay, heartbeat, and optional AG-UI SSE live tail. */
  async start(): Promise<void> {
    if (this.stopped) return;
    for (const [effectId, receipt] of this.pendingReceipts) {
      if (await this.submitReceipt(receipt)) this.forgetReceipt(effectId);
      if (this.stopped) return;
    }
    for (const effect of await this.listPendingEffects()) {
      await this.runEffect(effect);
    }
    this.heartbeatTimer ??= setInterval(() => void this.heartbeat(), 30_000);
    if (this.deps.streamUrl !== undefined && this.abortController === null) {
      this.abortController = new AbortController();
      void consumeClientEffectStream({
        fetchImpl: this.deps.fetchImpl,
        streamUrl: this.deps.streamUrl,
        headers: () => this.headers(),
        stopped: () => this.stopped,
        signal: this.abortController.signal,
        onEffect: (effect) => this.runEffect(effect),
      });
    }
  }

  async heartbeat(): Promise<boolean> {
    if (this.stopped) return false;
    for (const [effectId, receipt] of this.pendingReceipts) {
      if (await this.submitReceipt(receipt)) this.forgetReceipt(effectId);
    }
    try {
      const response = await this.deps.fetchImpl(
        `${this.deps.baseUrl}/v1/client-sessions/${this.deps.clientSessionId}/heartbeat`,
        {
          method: "POST",
          headers: this.controllerHeaders(),
          body: JSON.stringify(this.controllerCoordinates()),
        },
      );
      if ([400, 401, 403, 409, 410].includes(response.status)) this.stop();
      return response.ok;
    } catch {
      return false;
    }
  }

  async runEffect(effect: ClientEffectWire): Promise<void> {
    if (this.stopped || this.deps.controllerFenceToken === undefined) return;
    if (
      effect.client_binding_digest !== this.deps.clientBindingDigest ||
      this.deps.actionContractDigests?.[effect.action_name] !==
        effect.action_contract_digest
    ) {
      this.stop();
      return;
    }
    const effectId = effect.effect_id;
    if (this.executedEffects.has(effectId) || this.inflightEffects.has(effectId)) {
      return; // idempotent local dedup
    }
    this.inflightEffects.add(effectId);
    this.persistState();
    const executionRevision = this.uiRevision.current;
    try {
      if (effect.expected_ui_revision !== this.uiRevision.current) {
        this.rememberExecuted(effectId);
        const receipt: ReceiptSubmission = {
          effect_id: effectId,
          request_digest: effect.request_digest,
          status: "stale_ui_state",
          result: { expected: effect.expected_ui_revision, actual: this.uiRevision.current },
        };
        this.rememberReceipt(receipt);
        if (await this.submitReceipt(receipt)) this.forgetReceipt(effectId);
        return;
      }
      const result = await this.registry.dispatch(
        effect.action_name,
        effect.arguments,
      );
      if (this.uiRevision.current !== executionRevision) {
        this.rememberExecuted(effectId);
        const receipt: ReceiptSubmission = {
          effect_id: effectId,
          request_digest: effect.request_digest,
          status: "stale_ui_state",
          result: { expected: executionRevision, actual: this.uiRevision.current },
        };
        this.rememberReceipt(receipt);
        if (await this.submitReceipt(receipt)) this.forgetReceipt(effectId);
        return;
      }
      this.rememberExecuted(effectId);
      const receipt: ReceiptSubmission = {
        effect_id: effectId,
        request_digest: effect.request_digest,
        status: "succeeded",
        result,
      };
      this.rememberReceipt(receipt);
      if (await this.submitReceipt(receipt)) this.forgetReceipt(effectId);
    } catch (error) {
      this.rememberExecuted(effectId);
      const failure =
        error instanceof ClientRuntimeError &&
        error.code === CLIENT_SDK_ERRORS.ACTION_NOT_MOUNTED
          ? "unavailable"
          : "failed";
      const receipt: ReceiptSubmission = {
        effect_id: effectId,
        request_digest: effect.request_digest,
        status: failure as "unavailable" | "failed",
        result: {
          error:
            error instanceof ClientRuntimeError
              ? error.code
              : "client_action_failed",
        },
      };
      this.rememberReceipt(receipt);
      if (await this.submitReceipt(receipt)) this.forgetReceipt(effectId);
    } finally {
      this.inflightEffects.delete(effectId);
    }
  }

  /** Receipt submission retries until the server accepts it. */
  async submitReceipt(submission: ReceiptSubmission): Promise<boolean> {
    const outcome = await submitClientReceipt(
      this.deps,
      submission,
      () => this.stopped,
    );
    if (outcome === "rejected" && !this.stopped) this.stop();
    return outcome === "accepted";
  }

  stop(): void {
    if (!this.stopped) void this.releaseController();
    this.stopped = true;
    this.queuedMount = null;
    this.abortController?.abort();
    this.abortController = null;
    if (this.heartbeatTimer !== null) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = null;
  }

  get isStopped(): boolean {
    return this.stopped;
  }

  private rememberExecuted(effectId: string): void {
    this.inflightEffects.delete(effectId);
    this.executedEffects.add(effectId);
    this.persistState();
  }

  private rememberReceipt(receipt: ReceiptSubmission): void {
    this.pendingReceipts.set(receipt.effect_id, normalizeReceipt(receipt));
    this.persistState();
  }

  private forgetReceipt(effectId: string): void {
    this.pendingReceipts.delete(effectId);
    this.persistState();
  }

  private persistState(): void {
    this.stateStore.save({
      executedEffects: this.executedEffects,
      inflightEffects: this.inflightEffects,
      pendingReceipts: this.pendingReceipts,
    });
  }

  private headers(): Record<string, string> {
    return {
      "Content-Type": "application/json",
      "X-Zebra-Client-Session": this.deps.sessionCredential,
    };
  }

  private controllerHeaders(): Record<string, string> {
    return {
      ...this.headers(),
      "X-Zebra-Client-Fence": this.deps.controllerFenceToken ?? "",
    };
  }

  private controllerCoordinates(): Record<string, string> {
    if (
      this.deps.taskId === undefined ||
      this.deps.runId === undefined ||
      this.deps.runBindingId === undefined
    ) return {};
    return {
      task_id: this.deps.taskId,
      run_id: this.deps.runId,
      run_binding_id: this.deps.runBindingId,
    };
  }

  private async releaseController(): Promise<void> {
    if (this.deps.controllerFenceToken === undefined) return;
    try {
      await this.deps.fetchImpl(
        `${this.deps.baseUrl}/v1/client-sessions/${this.deps.clientSessionId}/release`,
        {
          method: "POST",
          headers: this.controllerHeaders(),
          body: JSON.stringify(this.controllerCoordinates()),
          keepalive: true,
        },
      );
    } catch {
      // The bounded lease remains the crash-safe fallback.
    }
  }

}

function browserSessionStorage(): Storage | undefined {
  try {
    return typeof sessionStorage === "undefined" ? undefined : sessionStorage;
  } catch {
    return undefined;
  }
}
