import { enforceOutgoingInput, HttpAgent, isRecognizedEvent, type AgentStateMutation, type AgentSubscriber, type HttpAgentConfig } from "@ag-ui/client";
import type { BaseEvent, RunAgentInput } from "@ag-ui/core";
import { concatMap, lastValueFrom, of, throwError, type Observable } from "rxjs";
import { assertAgUiBinding, validateAgUiPatch } from "./agui_events.js";
import { copyReadableJson } from "./readable_commands.js";
import { canonicalDigest } from "./canonical_digest.js";
import { readSseRecords, SseProtocolError } from "./sse_records.js";
import { readReliableAgUiStream, type StreamReadState } from "./sse_stream.js";
import type { ConversationStreamEvent } from "./conversation_stream.js";

export interface PreparedAgUiRun {
  operation: string;
  input: RunAgentInput;
}
export type AgUiAdmissionResult = PreparedAgUiRun | { operation: string; pending: true };
export interface AgUiHttpOptions {
  /** Fixed same-origin BFF observation path. Native coordinates/credentials stay at the BFF. */
  url: string;
  fetch?: typeof fetch;
  reliable?: boolean;
  admit: (operation: string, input: RunAgentInput) => Promise<AgUiAdmissionResult>;
  receipt: (operation: string) => Promise<AgUiAdmissionResult>;
  onEvent?: (event: BaseEvent) => void | Promise<void>;
  onApplied?: (agent: HttpAgent) => void | Promise<void>;
  onNotice?: (event: ConversationStreamEvent) => Promise<void>;
  onCursor?: (cursor: string | null) => void | Promise<void>;
}

/** Official HTTP/application pipeline; completion barriers never leave this instance. */
class AppliedHttpAgent extends HttpAgent {
  private barriers = new WeakSet<BaseEvent>();
  private applied: Promise<void> = Promise.resolve();
  private release: (() => void) | undefined;
  private rejectRecord: ((error: unknown) => void) | undefined;
  private rejectFatal: ((error: unknown) => void) | undefined;
  private hooks = new Set<Promise<unknown>>();
  private finalized: Promise<void> = Promise.resolve();
  private finish: (() => void) | undefined;
  private rejectFinished: ((error: unknown) => void) | undefined;
  private transport: Promise<void> = Promise.resolve();
  private outstanding = 0;
  private failure: { error: unknown } | undefined;
  private hasSnapshot = true;
  private originalSubscribers = new WeakMap<AgentSubscriber, AgentSubscriber>();
  private recovery: StreamReadState = { active: true };
  public cursor: string | null = null;
  constructor(private expected: RunAgentInput, private options: AgUiHttpOptions) {
    super({ url: options.url, threadId: expected.threadId, initialMessages: structuredClone(expected.messages),
      initialState: structuredClone(expected.state), debug: false });
    this.fetch = this.openResponse.bind(this);
  }
  clone(): AppliedHttpAgent {
    const cloned = super.clone() as AppliedHttpAgent;
    cloned.expected = structuredClone(this.expected);
    cloned.options = this.options;
    cloned.barriers = new WeakSet(); cloned.applied = Promise.resolve();
    cloned.release = undefined; cloned.rejectRecord = undefined; cloned.rejectFatal = undefined;
    cloned.hooks = new Set(); cloned.finalized = Promise.resolve(); cloned.finish = undefined; cloned.rejectFinished = undefined; cloned.transport = Promise.resolve();
    cloned.outstanding = 0; cloned.failure = undefined; cloned.hasSnapshot = true;
    cloned.recovery = { active: true }; cloned.cursor = null;
    cloned.originalSubscribers = new WeakMap();
    cloned.subscribers = this.subscribers.map(value => cloned.wrap(this.originalSubscribers.get(value) ?? value));
    cloned.abortController = new AbortController();
    cloned.fetch = cloned.openResponse.bind(cloned);
    return cloned;
  }
  private wrap(subscriber: AgentSubscriber): AgentSubscriber {
    const owner = this;
    const wrapped = new Proxy({} as AgentSubscriber, { get(_target, name) {
      const value = Reflect.get(subscriber, name) as unknown;
      if (typeof value !== "function") return value;
      return (...args: unknown[]) => {
        if (owner.failure) return;
        const pending = (async () => {
          try { return await value.apply(subscriber, args); }
          catch (error) { owner.fail(error); return { stopPropagation: true }; }
        })();
        owner.hooks.add(pending);
        void pending.finally(() => owner.hooks.delete(pending));
        return pending;
      };
    } });
    this.originalSubscribers.set(wrapped, subscriber);
    return wrapped;
  }
  private async drainHooks(): Promise<void> {
    while (this.hooks.size) await Promise.all([...this.hooks]);
    if (this.failure) throw this.failure.error;
  }
  protected async onFinalize(input: RunAgentInput, subscribers: AgentSubscriber[]): Promise<void> {
    try { await super.onFinalize(input, subscribers); await this.drainHooks(); this.finish?.(); }
    catch (error) { this.fail(error); }
  }
  subscribe(subscriber: AgentSubscriber) { return super.subscribe(this.wrap(subscriber)); }
  private fail(error: unknown): void { this.failure ??= { error }; this.rejectRecord?.(this.failure.error); this.rejectFatal?.(this.failure.error); this.rejectFinished?.(this.failure.error); super.abortRun(); }
  abortRun(): void { this.fail(new Error("AG-UI HTTP observation aborted")); }
  async runAgent(parameters?: Parameters<HttpAgent["runAgent"]>[0], subscriber?: AgentSubscriber) {
    if (parameters?.runId !== this.expected.runId) throw new Error("Observe the explicitly prepared public Run ID");
    if (this.failure) throw this.failure.error;
    let rejectFatal!: (error: unknown) => void;
    const fatal = new Promise<never>((_resolve, reject) => { rejectFatal = reject; });
    this.rejectFatal = rejectFatal;
    this.finalized = new Promise<void>((resolve, reject) => { this.finish = resolve; this.rejectFinished = reject; });
    void this.finalized.catch(() => {});
    void fatal.catch(() => {});
    const controller = parameters?.abortController ?? this.abortController;
    const abort = () => this.fail(controller.signal.reason ?? new Error("AG-UI HTTP observation aborted"));
    controller.signal.addEventListener("abort", abort, { once: true });
    if (controller.signal.aborted) abort();
    try {
      const result = await Promise.race([super.runAgent(parameters, subscriber ? this.wrap(subscriber) : undefined), fatal]);
      await Promise.race([this.finalized, fatal]);
      await Promise.race([this.transport, fatal]);
      return result;
    } finally { this.rejectFatal = undefined; controller.signal.removeEventListener("abort", abort); }
  }
  protected apply(input: RunAgentInput, events: Observable<BaseEvent>, subscribers: AgentSubscriber[]) {
    const guard: AgentSubscriber = { onEvent: async params => {
      try {
        await this.applied;
        if (this.failure) return { stopPropagation: true };
        if (this.barriers.has(params.event)) {
          await this.drainHooks();
          await this.options.onApplied?.(this);
          await this.drainHooks();
          if (--this.outstanding === 0) this.release?.();
          return { stopPropagation: true };
        }
        assertAgUiBinding({ threadId: params.event.threadId as string | undefined, runId: params.event.runId as string | undefined }, this.expected);
        if (params.event.type === "RUN_STARTED" && params.event.input) assertAgUiBinding(params.event.input as RunAgentInput, this.expected);
        this.hasSnapshot = validateAgUiPatch(params.event, params.messages, params.state, this.hasSnapshot);
        await this.options.onEvent?.(structuredClone(params.event));
        if (this.failure) return { stopPropagation: true };
      } catch (error) { this.fail(error); return { stopPropagation: true }; }
    } };
    return super.apply(input, events.pipe(concatMap(event => {
      if (this.failure) return throwError(() => this.failure!.error);
      this.outstanding++;
      const barrier = { type: "CUSTOM", name: "application-barrier", value: null } as BaseEvent;
      this.barriers.add(barrier);
      return of(event, barrier);
    })), [guard, ...subscribers]);
  }
  protected processApplyEvents(input: RunAgentInput, events: Observable<AgentStateMutation>, subscribers: AgentSubscriber[]) {
    return events.pipe(concatMap(mutation => {
      if (this.failure) return throwError(() => this.failure!.error);
      const applied = lastValueFrom(super.processApplyEvents(input, of(mutation), subscribers));
      this.applied = applied.then(() => {});
      void this.applied.catch(error => this.fail(error));
      return applied.then(() => mutation);
    }));
  }
  protected onError(_input: RunAgentInput, error: Error) { this.fail(error); return throwError(() => error); }
  private async openResponse(url: string, init: RequestInit): Promise<Response> {
    const owner = this;
    const signal = this.abortController.signal;
    const readResponse = () => {
      const headers = new Headers(init.headers);
      if (owner.cursor) headers.set("Last-Event-ID", owner.cursor);
      const { body: _body, ...readInit } = init;
      const native = owner.options.reliable ? { ...readInit, method: "GET", headers } : init;
      return (owner.options.fetch ?? globalThis.fetch)(url, { ...native, credentials: "same-origin", mode: "same-origin", redirect: "error", cache: "no-store" });
    };
    const response = await readResponse();
    if (!response.ok || !response.body) return response;
    let terminal = false;
    let closed = false;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        const canonical = async (raw: unknown) => {
          if (!isRecognizedEvent(raw as BaseEvent)) return;
          const event = raw as BaseEvent;
          const encoded = new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`);
          if (encoded.byteLength > 2_097_152) throw new SseProtocolError("Canonical AG-UI event exceeds byte budget");
          const applied = new Promise<void>((resolve, reject) => { owner.release = resolve; owner.rejectRecord = reject; });
          controller.enqueue(encoded);
          if (event.type === "RUN_FINISHED" || event.type === "RUN_ERROR") {
            terminal = true; closed = true; controller.close();
          }
          await applied;
          if (terminal) await owner.finalized;
          if (event.type === "RUN_ERROR" && String(event.code ?? "").startsWith("observation_")) {
            throw new SseProtocolError("Native observation failed; preserve the original operation");
          }
        };
        owner.transport = (async () => {
          if (owner.options.reliable) {
            let current = response;
            // ponytail: at most three read-only reconnects per observation. A higher
            // retry budget belongs to explicit Host recovery; admission is never repeated.
            for (let retries = 0; ; retries++) {
              if (!current.ok || !current.body) throw new Error("Reliable AG-UI observation unavailable");
              try { await readReliableAgUiStream(current.body, {
                signal, initialCursor: owner.cursor, recovery: owner.recovery, onCanonical: canonical,
                onNotice: async notice => {
                  try { await owner.options.onNotice?.(notice); }
                  catch (error) { owner.fail(error); throw error; }
                  if (notice.type === "CUSTOM" && notice.name === "zebra.observation.problem" &&
                      (notice.value as { retryable?: unknown })?.retryable !== true) {
                    throw new SseProtocolError("Reliable AG-UI observation rejected");
                  }
                },
                onCursor: async value => {
                  try { await owner.options.onCursor?.(value); owner.cursor = value; }
                  catch (error) { owner.fail(error); throw error; }
                },
              }); } catch (error) {
                if (signal.aborted || error instanceof SseProtocolError || owner.failure || retries >= 3) throw error;
              }
              if (terminal || signal.aborted) break;
              if (retries >= 3) throw new SseProtocolError("Reliable AG-UI observation incomplete");
              current = await readResponse();
            }
          } else for await (const record of readSseRecords(response.body!, 2_097_152, signal)) {
            let raw: unknown;
            try { raw = JSON.parse(record.data); } catch { throw new SseProtocolError("Invalid AG-UI JSON"); }
            await canonical(raw);
            if (terminal) break;
          }
          if (signal.aborted) throw signal.reason ?? new Error("AG-UI HTTP observation aborted");
          if (!terminal) throw new SseProtocolError("AG-UI observation ended before its terminal");
          if (!closed) { closed = true; controller.close(); }
        })().catch(error => { owner.fail(error); if (!closed) { closed = true; controller.error(error); } });
      },
      cancel(reason) { owner.fail(reason ?? new Error("AG-UI HTTP body cancelled")); },
    }, { highWaterMark: 0 });
    return new Response(stream, { status: response.status, headers: response.headers });
  }
}

/** Capture native intent once, reconcile its original receipt, then explicitly observe
 * the returned public Run with a retained official HttpAgent. No POST retries. */
export function createAgUiHttpClient(options: AgUiHttpOptions) {
  if (!/^\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_-]+$/.test(options.url) || options.url.length > 512) {
    throw new Error("AG-UI observation requires a fixed same-origin BFF path");
  }
  const fetchImpl = options.fetch ?? globalThis.fetch;
  let pending: { operation: string; input: RunAgentInput } | undefined;
  let ready: PreparedAgUiRun | undefined;
  let agent: AppliedHttpAgent | undefined;
  let busy = false;
  let consumed: string | undefined;

  async function accept(result: AgUiAdmissionResult): Promise<AgUiAdmissionResult> {
    if (!pending || result.operation !== pending.operation) throw new Error("Admission receipt belongs to another intent");
    if (!("pending" in result)) {
      const { runId: _native, ...original } = pending.input;
      const { runId: publicId, ...accepted } = result.input;
      if (!/^agui:[0-9a-f]{64}$/.test(publicId) || await canonicalDigest(original) !== await canonicalDigest(accepted)) {
        throw new Error("Prepared public binding conflicts with captured native input");
      }
      if (agent && agent.threadId !== result.input.threadId) throw new Error("Use one official agent per authorized thread");
      if (!ready || ready.operation !== result.operation) agent = new AppliedHttpAgent(result.input, options);
      ready = structuredClone(result);
    }
    return structuredClone(result);
  }

  return {
    get agent(): HttpAgent | undefined { return agent; },
    get pendingOperation(): string | undefined { return pending?.operation; },
    get cursor(): string | null { return agent?.cursor ?? null; },
    /** Install the current BFF's original prepared locator; performs no admission or IO. */
    async attachPrepared(result: PreparedAgUiRun): Promise<PreparedAgUiRun> {
      if (pending || ready || agent || busy || consumed) throw new Error("Attach a prepared receipt only to a fresh client");
      if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(result.operation) ||
          !/^agui:[0-9a-f]{64}$/.test(result.input.runId) ||
          result.input.protocolVersion !== undefined && result.input.protocolVersion !== "1.0") {
        throw new Error("Prepared receipt requires its original operation and public protocol 1.0 Run");
      }
      const input = enforceOutgoingInput(copyReadableJson({ ...result.input, protocolVersion: "1.0" }) as unknown as RunAgentInput);
      pending = { operation: result.operation, input };
      ready = { operation: result.operation, input: structuredClone(input) };
      agent = new AppliedHttpAgent(input, options);
      return structuredClone(ready);
    },
    async admit(input: RunAgentInput): Promise<AgUiAdmissionResult> {
      if (pending || busy) throw new Error("Reconcile the original admission before creating another intent");
      if (agent && agent.threadId !== input.threadId) throw new Error("Use one official agent per authorized thread");
      if (input.protocolVersion !== undefined && input.protocolVersion !== "1.0") throw new Error("Prepared native input requires protocol 1.0");
      const captured = enforceOutgoingInput(copyReadableJson({ ...input, protocolVersion: "1.0" }) as unknown as RunAgentInput);
      pending = { operation: globalThis.crypto.randomUUID(), input: captured };
      busy = true;
      try { return accept(await options.admit(pending.operation, structuredClone(captured))); }
      finally { busy = false; }
    },
    async reconcile(): Promise<AgUiAdmissionResult> {
      if (!pending || busy) throw new Error("No idle original admission to reconcile");
      busy = true;
      try { return accept(await options.receipt(pending.operation)); }
      finally { busy = false; }
    },
    async observe(signal?: AbortSignal): Promise<HttpAgent> {
      if (!ready || busy || consumed === ready.operation) throw new Error("Observe an accepted public Run exactly once");
      const current = ready;
      if (agent && agent.threadId !== current.input.threadId) throw new Error("Use one official agent per authorized thread");
      busy = true;
      consumed = current.operation;
      const abort = new AbortController();
      const aborted = () => abort.abort(signal?.reason);
      signal?.addEventListener("abort", aborted, { once: true });
      if (signal?.aborted) aborted();
      try {
        const { runId, tools, context, forwardedProps, resume } = current.input;
        await agent!.runAgent({ runId, tools, context, forwardedProps, abortController: abort, ...(resume ? { resume } : {}) });
        pending = undefined; ready = undefined;
        return agent!;
      } finally { busy = false; signal?.removeEventListener("abort", aborted); }
    },
  };
}
