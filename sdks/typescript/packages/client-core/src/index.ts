export { createAuthenticatedRuntime, type AuthenticatedRuntimeOptions } from "./auth_lifecycle.ts";
export { createBFFAuth, type BFFAuthState } from "./bff_auth.ts";
export { createCommandRecoveryInbox, type PendingRequest, type PendingRequestsPage, type UnknownHandling } from "./request_discovery.ts";
import { CommandRecovery, submitRecoverableCommand, type CommandRecoveryView } from "./command_recovery.ts";
import { copyReadableJson, sendReadableCommand, type ReadableCommandOptions, type ReadableSurface } from "./readable_commands.ts";
import { streamObserverOptions, type StreamObserverOptions } from "./conversation_stream.ts";
/** React-free browser runtime (ADR-CLIENT-01).
 * Never stores Host Grants; handlers and profiles must be mounted and fenced.
 * Effects dedupe, receipts retry, and expiry stops execution.
 */
import {
  CLIENT_SDK_ERRORS,
  type ClientEffectWire,
  type ReceiptSubmission,
  type RuntimeBrowserConfig,
} from "@zebra-agent/contracts";
import { ClientRuntimeStateStore, UiRevisionClock } from "./runtime_state.ts";
import { consumeClientEffectStream } from "./sse_stream.ts";
import { normalizeReceipt, submitClientReceipt } from "./receipt_transport.ts";
import { synchronizedMount, drainSurfaceWork, sendRuntimeMount, releaseRuntimeController } from "./runtime_mount.ts";
import { runtimeDependencies } from "./runtime_configuration.ts";
import { clientHeaders, readPendingEffects } from "./runtime_transport.ts";
import { MountedActionRegistry } from "./action_registry.ts";
import { ClientRuntimeError } from "./errors.ts";
export { scrubResult } from "./result_security.ts";
export { canonicalDigest } from "./canonical_digest.ts";
export { MountedActionRegistry, type ClientActionHandler } from "./action_registry.ts";
export { ClientRuntimeError } from "./errors.ts";
export { UiRevisionClock } from "./runtime_state.ts";
export interface MountOptions {
  frontendAppId: string;
  profileRevision: number;
  profileDigest: string;
  mountedActions: readonly string[];
  mountedReadables?: readonly string[];
}
export interface ClientRuntimeDependencies extends StreamObserverOptions {
  fetchImpl: typeof fetch;
  baseUrl: string;
  clientSessionId: string;
  sessionCredential: string;
  mode?: "legacy" | undefined;
  controllerFenceToken?: string | undefined;
  taskId?: string | undefined;
  runId?: string | undefined;
  runBindingId?: string | undefined;
  clientBindingDigest?: string | undefined;
  actionContractDigests?: Readonly<Record<string, string>> | undefined;
  initialUiRevision?: number | undefined;
  streamUrl?: string | undefined;
  storage?: Storage | undefined;
}
/** Preserve the original required-secret DI type for existing server/legacy consumers. */
export type BrowserRuntimeDependencies = ClientRuntimeDependencies | (
  Omit<ClientRuntimeDependencies, "mode" | "sessionCredential" | "controllerFenceToken" | "streamUrl"> & {
    mode: "bff";
    controller: boolean;
    surfaceMetadataVersion?: 1 | undefined;
    clientStateVersion?: 1 | undefined;
    commandRecoveryVersion?: 1 | undefined;
    sessionCredential?: never;
    controllerFenceToken?: never;
    streamUrl?: never;
  }
);
export type ClientRuntimeStatus = "connecting" | "ready" | "unavailable" | "stopped";
export class ZebraClientRuntime {
  readonly registry = new MountedActionRegistry();
  readonly readableNames = new Set<string>();
  readonly uiRevision: UiRevisionClock;
  private executedEffects: Set<string>;
  private inflightEffects: Set<string>;
  private recoveredInflightEffects: Set<string>;
  private pendingReceipts: Map<string, ReceiptSubmission>;
  private lastEventId: string | null;
  private stateStore: ClientRuntimeStateStore;
  private mountedProfileDigest: string | null = null;
  private abortController: AbortController | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private queuedMount: MountOptions | null = null;
  private mountFlush: Promise<void> | null = null;
  private deps: BrowserRuntimeDependencies;
  private stopped = false;
  private readonly jobs = new Set<Promise<unknown>>();
  private mounting = false;
  private bindingRevision = 0;
  private readonly readableValues = new Map<string, Record<string, unknown>>();
  private readableSurface: ReadableSurface | null = null;
  private readonly commandRecovery: CommandRecovery | null;
  private polling = false;
  private heartbeating = false;
  private status: ClientRuntimeStatus = "connecting";
  private readonly statusListeners = new Set<() => void>();
  readonly getStatus = (): ClientRuntimeStatus => this.status;
  readonly subscribeStatus = (listener: () => void): (() => void) => {
    this.statusListeners.add(listener);
    return () => { this.statusListeners.delete(listener); };
  };
  private setStatus(status: ClientRuntimeStatus): void {
    if (this.status === status) return;
    this.status = status;
    for (const listener of this.statusListeners) listener();
  }
  private get controls(): boolean {
    return this.deps.mode === "bff" ? this.deps.controller === true : this.deps.controllerFenceToken !== undefined;
  }
  private get surfacePending(): boolean { return this.mounting || synchronizedMount(this.deps) && this.bindingRevision === 0; }
  constructor(deps: BrowserRuntimeDependencies) {
    if (deps.mode === "bff" && deps.surfaceMetadataVersion !== undefined && (deps.surfaceMetadataVersion !== 1 || deps.initialUiRevision === undefined)) throw new ClientRuntimeError("invalid_surface_version", "explicit surface version1 and initial revision required");
    if (deps.mode === "bff" && (deps.sessionCredential !== undefined || deps.controllerFenceToken !== undefined)) {
      throw new ClientRuntimeError("invalid_bff_config", "BFF runtime cannot hold native secrets");
    }
    if (deps.mode === "bff" && deps.clientStateVersion !== undefined && (deps.clientStateVersion !== 1 || deps.surfaceMetadataVersion !== 1)) throw new ClientRuntimeError("invalid_readable_version", "Readable version1 requires synchronized BFF surface");
    if (deps.mode === "bff" && deps.commandRecoveryVersion !== undefined && (deps.commandRecoveryVersion !== 1 || deps.clientStateVersion !== 1)) throw new ClientRuntimeError("invalid_recovery_version", "recovery1 requires Readable1");
    this.commandRecovery = deps.mode === "bff" && deps.commandRecoveryVersion === 1 ? new CommandRecovery(deps.storage, deps.clientSessionId, deps.taskId!, deps.runId!, deps.fetchImpl, `${deps.baseUrl}/agui/threads/${deps.taskId}/runs/${encodeURIComponent(deps.runId!)}/commands/receipt`) : null;
    this.deps = deps;
    this.uiRevision = new UiRevisionClock(deps.initialUiRevision);
    this.stateStore = new ClientRuntimeStateStore(deps.storage, deps.clientSessionId);
    const restored = this.stateStore.load();
    this.executedEffects = restored.executedEffects;
    this.inflightEffects = new Set();
    this.recoveredInflightEffects = restored.inflightEffects;
    this.pendingReceipts = restored.pendingReceipts;
    this.lastEventId = restored.lastEventId;
    if (this.commandRecovery?.pending().length) this.disconnect();
  }
  static fromConfig(config: RuntimeBrowserConfig & StreamObserverOptions): ZebraClientRuntime {
    return new ZebraClientRuntime(runtimeDependencies(config));
  }
  /** Mount declares the page's actions; digest drift stops mounting. */
  async mount(options: MountOptions): Promise<void> {
    this.commandRecovery?.ensureClear();
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
    const sync = synchronizedMount(this.deps);
    if (sync && this.mounting) throw new ClientRuntimeError("surface_busy", "mount is already in progress");
    if (sync) { this.mounting = true; this.setStatus("connecting"); }
    try {
      if (sync) {
        await drainSurfaceWork(this.jobs, () => this.stopped);
        if (this.pendingReceipts.size || this.recoveredInflightEffects.size) throw new ClientRuntimeError("surface_unresolved", "reconcile old receipts before remounting");
      }
      if (this.stopped) return;
      const metadata = await sendRuntimeMount(this.deps, options, this.uiRevision.bump(), this.bindingRevision);
      if (this.stopped) return;
      if (metadata) {
        this.deps = { ...this.deps, clientBindingDigest: metadata.binding_digest, actionContractDigests: metadata.action_contract_digests };
        this.bindingRevision = metadata.binding_revision;
        this.readableSurface = { frontendAppId: options.frontendAppId, clientSessionId: this.deps.clientSessionId, taskId: this.deps.taskId!, runId: this.deps.runId!, metadata };
      }
    } catch (error) { if (sync) this.disconnect(); throw error; }
    finally { this.mounting = false; }
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
  mountReadable(name: string, value?: Record<string, unknown>): void {
    if (this.deps.mode === "bff" && this.deps.clientStateVersion === 1) {
      if (this.readableNames.has(name)) throw new ClientRuntimeError("readable_already_mounted", "Readable already mounted");
      this.readableValues.set(name, copyReadableJson(value));
    }
    this.readableNames.add(name);
  }
  updateReadable(name: string, value: Record<string, unknown>): void {
    if (this.deps.mode !== "bff" || this.deps.clientStateVersion !== 1) return;
    if (!this.readableNames.has(name)) throw new ClientRuntimeError("readable_not_mounted", "Readable not mounted");
    this.readableValues.set(name, copyReadableJson(value));
  }
  async submitReadableCommand(options: ReadableCommandOptions) {
    await this.mountFlush;
    if (this.stopped || this.surfacePending || this.deps.mode !== "bff" || this.deps.clientStateVersion !== 1 || !this.readableSurface) throw new ClientRuntimeError("readable_not_ready", "Readable surface not ready");
    return this.track(submitRecoverableCommand(this.commandRecovery, options.idempotencyKey,
      before => sendReadableCommand(this.deps.fetchImpl, this.deps.baseUrl, this.readableSurface!, options, this.readableValues, before), () => this.disconnect()));
  }
  get readableCommandRecovery(): CommandRecoveryView | null { return this.commandRecovery; }
  unmountReadable(name: string): void {
    this.readableNames.delete(name); this.readableValues.delete(name);
  }
  /** Reconnect replay of pending effects; each executes at most once. */
  async listPendingEffects(): Promise<ClientEffectWire[]> {
    const response = await this.deps.fetchImpl(
      `${this.deps.baseUrl}/v1/client-sessions/${this.deps.clientSessionId}/effects`,
      { headers: this.headers() },
    );
    if (!response.ok) {
      if ([400, 401, 403, 404, 410, 422].includes(response.status)) this.stop();
      throw new ClientRuntimeError("effects_unavailable", `effect poll rejected (${response.status})`);
    }
    return readPendingEffects(response, this.deps.mode === "bff");
  }

  /** Start durable replay, heartbeat, and optional AG-UI SSE live tail. */
  async start(): Promise<void> {
    if (this.stopped) return;
    if (this.controls) for (const [effectId, receipt] of this.pendingReceipts) {
      if (await this.submitReceipt(receipt)) this.forgetReceipt(effectId);
      if (this.stopped) return;
    }
    try { await this.mountFlush; } catch { this.stop(); return; }
    if (this.stopped) return;
    // V2 reconciles the current pending set at its awaited recovery boundary.
    if (this.deps.streamVersion !== 2 || this.deps.streamUrl === undefined) await this.poll();
    this.heartbeatTimer ??= setInterval(() => void this.heartbeat(), 30_000);
    if (this.deps.streamUrl === undefined && this.pollTimer === null) {
      // ponytail: durable HTTP polling is the universal fallback; Hosts may
      // upgrade to the same-origin AG-UI stream without changing handlers.
      this.pollTimer = setInterval(() => void this.poll(), 1_000);
    }
    if (this.deps.streamUrl !== undefined && this.abortController === null) {
      this.abortController = new AbortController();
      void consumeClientEffectStream({
        fetchImpl: this.deps.fetchImpl,
        streamUrl: this.deps.streamUrl,
        headers: () => this.headers(),
        stopped: () => this.stopped,
        signal: this.abortController.signal,
        initialEventId: this.lastEventId,
        ...streamObserverOptions(this.deps),
        onCursor: (eventId) => { this.lastEventId = eventId; this.persistState(); },
        onCursorRecovered: () => this.poll(),
        onTerminalRejection: () => this.stop(),
        onEffect: (effect) => this.runEffect(effect),
      });
    }
  }

  /** Fetch and execute the current durable pending set once. */
  poll(): Promise<void> { return this.track(this.pollOnce()); }

  private async pollOnce(): Promise<void> {
    if (this.stopped || this.surfacePending || this.polling) return;
    this.polling = true;
    try {
      const effects = await this.listPendingEffects();
      for (const effect of effects) await this.runEffect(effect);
      if (!this.stopped && !this.mounting) this.setStatus("ready");
    } catch {
      if (!this.stopped) this.setStatus("unavailable");
    } finally { this.polling = false; }
  }

  heartbeat(): Promise<boolean> { return this.track(this.heartbeatOnce()); }

  private async heartbeatOnce(): Promise<boolean> {
    if (this.stopped || this.surfacePending || this.heartbeating) return false;
    this.heartbeating = true;
    try {
      if (this.controls) for (const [effectId, receipt] of this.pendingReceipts) {
        if (await this.submitReceipt(receipt)) this.forgetReceipt(effectId);
      }
      if (this.stopped) return false;
      const response = await this.deps.fetchImpl(
        `${this.deps.baseUrl}/v1/client-sessions/${this.deps.clientSessionId}/heartbeat`,
        { method: "POST", headers: this.controllerHeaders(), body: JSON.stringify(this.controllerCoordinates()) },
      );
      if ([400, 401, 403, 409, 410].includes(response.status)) this.stop();
      if (!response.ok && !this.stopped) this.setStatus("unavailable");
      return response.ok;
    } catch {
      if (!this.stopped) this.setStatus("unavailable");
      return false;
    } finally { this.heartbeating = false; }
  }

  runEffect(effect: ClientEffectWire): Promise<void> { return this.track(this.executeEffect(effect)); }

  private async executeEffect(effect: ClientEffectWire): Promise<void> {
    if (this.stopped || this.surfacePending || !this.controls) return;
    if (
      effect.surface_instance_id !== this.deps.clientSessionId ||
      effect.task_id !== this.deps.taskId ||
      effect.run_id !== this.deps.runId ||
      effect.client_binding_digest !== this.deps.clientBindingDigest ||
      effect.capability_version !== effect.action_contract_digest ||
      this.deps.actionContractDigests?.[effect.action_name] !==
        effect.action_contract_digest
    ) {
      this.stop();
      return;
    }
    const effectId = effect.effect_id;
    const deadline = Date.parse(effect.deadline);
    if (
      !Number.isFinite(deadline) ||
      effect.deadline !== effect.expires_at ||
      deadline <= Date.now()
    ) {
      this.rememberExecuted(effectId);
      return;
    }
    if (this.executedEffects.has(effectId) || this.inflightEffects.has(effectId)) {
      return; // idempotent local dedup
    }
    if (this.recoveredInflightEffects.delete(effectId)) {
      this.rememberExecuted(effectId);
      const receipt: ReceiptSubmission = {
        effect_id: effectId,
        request_digest: effect.request_digest,
        status: "unavailable",
        result: { error: "interrupted_requires_confirmation" },
      };
      this.rememberReceipt(receipt);
      if (await this.submitReceipt(receipt)) this.forgetReceipt(effectId);
      return;
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
  submitReceipt(submission: ReceiptSubmission): Promise<boolean> {
    if (synchronizedMount(this.deps) && this.mounting && !this.pendingReceipts.has(submission.effect_id)) return Promise.resolve(false);
    return this.track(this.sendReceipt(submission));
  }

  private async sendReceipt(submission: ReceiptSubmission): Promise<boolean> {
    const outcome = await submitClientReceipt(
      this.deps,
      submission,
      () => this.stopped,
    );
    if (outcome === "rejected" && !this.stopped) this.stop();
    return outcome === "accepted";
  }

  stop(): void { this.shutdown(true); }

  /** Stop local work while preserving the controller lease for reconnect. */
  disconnect(): void { this.shutdown(false); }

  private shutdown(releaseController: boolean): void {
    if (!this.stopped && releaseController) void this.releaseController();
    this.stopped = true;
    this.setStatus("stopped");
    this.queuedMount = null;
    this.abortController?.abort();
    this.abortController = null;
    if (this.heartbeatTimer !== null) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = null;
    if (this.pollTimer !== null) clearInterval(this.pollTimer);
    this.pollTimer = null;
  }

  get isStopped(): boolean { return this.stopped; }

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
      lastEventId: this.lastEventId,
    });
  }

  private headers(): Record<string, string> {
    return clientHeaders(this.deps);
  }

  private controllerHeaders(): Record<string, string> {
    return clientHeaders(this.deps, true);
  }

  private controllerCoordinates(): Record<string, string> {
    if (
      !this.controls ||
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
  private releaseController(): Promise<void> {
    return this.controls ? releaseRuntimeController(this.deps, this.controllerCoordinates()) : Promise.resolve();
  }
  private track<T>(work: Promise<T>): Promise<T> {
    this.jobs.add(work);
    void work.then(() => this.jobs.delete(work), () => this.jobs.delete(work));
    return work;
  }
}
export { ConversationStreamReducer, STREAM_V2_CAPABILITIES } from "./conversation_stream.ts";
export type { ConversationMessage, ConversationStreamEvent } from "./conversation_stream.ts";
export { openClientSurface, type ClientSurfaceOpenOptions, type ClientSurfaceOpened, mountClientSurface, type ClientSurfaceOptions, type ClientSurfaceAdmission, type ClientSurfaceMount } from "./client_surface.ts";
export { publicClientSurfaceMetadata, validateSurfaceMetadata, type PublicClientSurfaceMetadata } from "./surface_metadata.ts";
export { nativeReadableCommand, type ReadableCommandOptions, type ReadableCommandResult } from "./readable_commands.ts";
export type { CommandRecoveryView } from "./command_recovery.ts";
