import { AbstractAgent, buildResumeArray, enforceOutgoingInput, isInterruptExpired, type AgentStateMutation, type AgentSubscriber } from "@ag-ui/client";
import type { BaseEvent, Interrupt, Message, ResumeEntry, RunAgentInput, State } from "@ag-ui/core";
import { concatMap, lastValueFrom, of, Subject, takeUntil, throwError, type Observable } from "rxjs";
import { assertAgUiBinding, boundAgUiEvents, validateAgUiPatch, type AgUiEventSource, type AgUiRunBinding } from "./agui_events.js";

export interface StandardAgUiConsumerOptions {
  signal?: AbortSignal;
  initialMessages?: Message[];
  initialState?: State;
  /** Pre-apply normalized events; snapshot still reflects earlier accepted events. Receives a copy. */
  onEvent?: (event: BaseEvent) => void | Promise<void>;
  /** After application/final status; awaited copies. A stalled callback permits at most
   * one source event batch before pulling the next record. */
  onSnapshot?: (snapshot: StandardAgUiSnapshot) => void | Promise<void>;
}
export interface StandardAgUiSnapshot extends AgUiRunBinding {
  messages: Message[];
  state: State;
  pendingInterrupts: Interrupt[];
  /** Observation/application state only; never execution or durable-commit authority. */
  status: "idle" | "consuming" | "incomplete" | "finished" | "error" | "failed";
  terminal?: BaseEvent;
}

/** A private in-memory agent reuses the official apply/drain/error pipeline without HTTP. */
class RecordedAgUiAgent extends AbstractAgent {
  private readonly stopped = new Subject<void>();
  private cleanup: (() => void) | undefined;
  private previousApplied: Promise<void> = Promise.resolve();
  private readonly barriers = new WeakSet<BaseEvent>();
  private outstanding = 0;
  private releaseBarrier: (() => void) | undefined;
  public async acknowledgeBarrier(event: BaseEvent): Promise<boolean> {
    if (!this.barriers.has(event)) return false;
    await this.previousApplied;
    if (--this.outstanding === 0) this.releaseBarrier?.();
    return true;
  }
  constructor(private readonly source: AgUiEventSource, private readonly binding: AgUiRunBinding,
    private readonly onApplied: () => void | Promise<void>, initial: StandardAgUiConsumerOptions) {
    super({ threadId: binding.threadId, agentId: "zebra-standard-consumer", debug: false, initialMessages: structuredClone(initial.initialMessages ?? []), initialState: structuredClone(initial.initialState ?? {}) });
  }
  run(_input: RunAgentInput): Observable<BaseEvent> {
    const owner = this;
    const source = { async *[Symbol.asyncIterator]() {
      const asyncSource = owner.source as AsyncIterable<unknown>;
      const iterator = typeof asyncSource[Symbol.asyncIterator] === "function"
        ? asyncSource[Symbol.asyncIterator]() : (owner.source as Iterable<unknown>)[Symbol.iterator]();
      let returned: Promise<IteratorResult<unknown>> | undefined;
      const requestReturn = () => returned ??= Promise.resolve().then(() => iterator.return?.() ?? { done: true, value: undefined });
      owner.cleanup = () => { owner.releaseBarrier?.(); void requestReturn().catch(() => {}); };
      let failed = false;
      try {
        while (true) {
          const next = await iterator.next();
          if (next.done) return;
          const acknowledged = new Promise<void>(resolve => owner.releaseBarrier = resolve);
          yield next.value;
          if (owner.outstanding) await acknowledged;
        }
      } catch (error) { failed = true; throw error; }
      finally { try { await requestReturn(); } catch (error) { if (!failed) throw error; } }
    } };
    return boundAgUiEvents(source, this.binding).pipe(takeUntil(this.stopped));
  }
  public abortRun(): void {
    this.releaseBarrier?.();
    this.stopped.next();
    this.stopped.complete();
    this.cleanup?.();
  }
  public waitForPreviousApplied(): Promise<void> { return this.previousApplied; }
  protected apply(input: RunAgentInput, events: Observable<BaseEvent>, subscribers: AgentSubscriber[]) {
    // ponytail: upstream has no completion hook for events without mutations.
    // Insert identity-only barriers AFTER enforcement/chunking/verification. They
    // drain prior application, never enter user hooks/history/wire, and pace pulls.
    return super.apply(input, events.pipe(concatMap(event => {
      this.outstanding++;
      const barrier = { type: "CUSTOM", name: "application-barrier", value: null } as BaseEvent;
      this.barriers.add(barrier);
      return of(event, barrier);
    })), subscribers);
  }

  protected processApplyEvents(input: RunAgentInput, events: Observable<AgentStateMutation>, subscribers: AgentSubscriber[]) {
    return events.pipe(concatMap(mutation => {
      // Install the barrier synchronously before defaultApply can begin the next event.
      const applied = lastValueFrom(super.processApplyEvents(input, of(mutation), subscribers))
        .then(() => this.onApplied());
      this.previousApplied = applied.then(() => {});
      void this.previousApplied.catch(() => {});
      return applied.then(() => mutation);
    }));
  }
  // This reader has no navigation/fetch abort to suppress: every source failure is observable.
  protected onError(_input: RunAgentInput, error: Error) { return throwError(() => error); }
}

/** One instance consumes one authorized protocol Run, from a recording or live iterable.
 * Failure unsubscribes and requests iterator cleanup; caller-owned IO/callback promises
 * cannot be forcibly cancelled. An AbortSignal rejects promptly and requests cleanup. */
export class StandardAgUiConsumer {
  private readonly binding: AgUiRunBinding;
  private agent: RecordedAgUiAgent | undefined;
  private status: StandardAgUiSnapshot["status"] = "idle";
  private terminal: BaseEvent | undefined;

  constructor(binding: AgUiRunBinding, private readonly options: StandardAgUiConsumerOptions = {}) {
    if (typeof binding.threadId !== "string" || typeof binding.runId !== "string") {
      throw new Error("AG-UI binding requires threadId and runId strings");
    }
    this.binding = { ...binding };
  }

  get snapshot(): StandardAgUiSnapshot {
    return structuredClone({ ...this.binding, messages: this.agent?.messages ?? [], state: this.agent ? this.agent.state : {},
      pendingInterrupts: this.agent?.pendingInterrupts ?? [], status: this.status,
      ...(this.terminal ? { terminal: this.terminal } : {}) });
  }

  async consume(source: AgUiEventSource): Promise<StandardAgUiSnapshot> {
    if (this.agent) throw new Error("Consume a bound AG-UI Run only once; use a new instance for another Run");
    let hasStateSnapshot = this.options.initialState !== undefined;
    let applicationError: { error: unknown } | undefined;
    let acceptedTerminal: BaseEvent | undefined;
    let rejectFatal!: (error: unknown) => void;
    const fatal = new Promise<never>((_resolve, reject) => { rejectFatal = reject; });
    void fatal.catch(() => {});
    const failApplication = (error: unknown) => {
      applicationError ??= { error };
      rejectFatal(applicationError.error);
      this.agent!.abortRun();
    };
    this.agent = new RecordedAgUiAgent(source, this.binding, async () => {
      if (applicationError) return;
      try { await this.options.onSnapshot?.(this.snapshot); }
      catch (error) { failApplication(error); throw error; }
    }, this.options);
    this.status = "consuming";
    const signal = this.options.signal;
    const abort = () => failApplication(signal?.reason ?? new Error("AG-UI consumption aborted"));
    signal?.addEventListener("abort", abort, { once: true });
    try {
      if (signal?.aborted) throw signal.reason ?? new Error("AG-UI consumption aborted");
      await Promise.race([this.agent.runAgent({ runId: this.binding.runId }, {
        onEvent: async ({ event, messages, state }) => {
          try {
            await this.agent!.waitForPreviousApplied();
            if (applicationError || await this.agent!.acknowledgeBarrier(event)) return { stopPropagation: true };
            // Upstream warns and skips failed patches. Preflight without replacing its reducer.
            hasStateSnapshot = validateAgUiPatch(event, messages, state, hasStateSnapshot);
            await this.options.onEvent?.(structuredClone(event));
            if (applicationError) return { stopPropagation: true };
            if (event.type === "RUN_FINISHED" || event.type === "RUN_ERROR") acceptedTerminal = structuredClone(event);
          } catch (error) {
            // Upstream swallows subscriber exceptions outside test mode. Stop explicitly,
            // suppress queued mutations, and rethrow once the official drain has completed.
            failApplication(error);
            return { stopPropagation: true };
          }
        },
      }), fatal]);
      if (applicationError) throw applicationError.error;
      this.terminal = acceptedTerminal;
      this.status = this.terminal?.type === "RUN_FINISHED" ? "finished" : this.terminal ? "error" : "incomplete";
      await Promise.race([this.options.onSnapshot?.(this.snapshot), fatal]);
      if (signal?.aborted) throw signal.reason ?? new Error("AG-UI consumption aborted");
      return this.snapshot;
    } catch (error) {
      this.status = "failed";
      throw error;
    } finally { signal?.removeEventListener("abort", abort); }
  }

  /** Prepare only; the application remains responsible for authority and sending the next Run. */
  prepareResume(interruptedRun: AgUiRunBinding, entries: ResumeEntry[], now = new Date()): ResumeEntry[] {
    assertAgUiBinding(interruptedRun, this.binding);
    if (interruptedRun.threadId !== this.binding.threadId || interruptedRun.runId !== this.binding.runId) {
      throw new Error("Resume binding must name the interrupted thread/run");
    }
    if (!Number.isFinite(now.getTime())) throw new Error("Resume expiry requires a valid current time");
    const interrupts = this.agent?.pendingInterrupts ?? [];
    if (this.status !== "finished" || !interrupts.length) throw new Error("No completed interrupted Run to resume");
    if (new Set(interrupts.map(i => i.id)).size !== interrupts.length) throw new Error("duplicate interrupt ids");
    const responses: Parameters<typeof buildResumeArray>[1] = Object.create(null);
    for (const entry of entries) {
      if (Object.hasOwn(responses, entry.interruptId)) throw new Error("duplicate resume interrupt id");
      if (entry.payload === null) throw new Error("Resume payload must be non-null JSON");
      if (entry.payload !== undefined) assertJson(entry.payload);
      const { interruptId, ...response } = entry;
      responses[interruptId] = response;
    }
    const resume = buildResumeArray(interrupts, responses);
    for (const interrupt of interrupts) {
      const response = responses[interrupt.id]!;
      if (response.status !== "cancelled" &&
          (isInterruptExpired(interrupt, now) || (interrupt.expiresAt !== undefined && !Number.isFinite(Date.parse(interrupt.expiresAt))))) {
        throw new Error(`Interrupt ${interrupt.id} expired or has an invalid expiry; cancel it to continue`);
      }
    }
    return enforceOutgoingInput({ threadId: this.binding.threadId, runId: this.binding.runId, protocolVersion: "1.0",
      messages: [], state: {}, tools: [], context: [], forwardedProps: {}, resume }).resume!;
  }
}


// Official arbitrary-data fields use z.any(); the in-memory resume boundary still requires JSON.
function assertJson(value: unknown, ancestors = new Set<object>()): void {
  if (value === null || typeof value === "string" || typeof value === "boolean" ||
      (typeof value === "number" && Number.isFinite(value))) return;
  if (typeof value !== "object" || ancestors.has(value) ||
      (!Array.isArray(value) && ![Object.prototype, null].includes(Object.getPrototypeOf(value)))) {
    throw new Error("Resume payload must contain only finite, acyclic JSON values");
  }
  ancestors.add(value);
  for (const child of Array.isArray(value) ? value : Object.values(value)) assertJson(child, ancestors);
  ancestors.delete(value);
}
