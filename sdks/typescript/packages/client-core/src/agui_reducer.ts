import { AbstractAgent, buildResumeArray, enforceOutgoingInput, isInterruptExpired, type AgentStateMutation, type AgentSubscriber } from "@ag-ui/client";
import type { ActivityDeltaEvent, BaseEvent, Interrupt, Message, ResumeEntry, RunAgentInput, State, StateDeltaEvent } from "@ag-ui/core";
import { concatMap, lastValueFrom, of, Subject, takeUntil, tap, throwError, type Observable } from "rxjs";
import jsonpatch from "fast-json-patch";
import { assertAgUiBinding, boundAgUiEvents, type AgUiEventSource, type AgUiRunBinding } from "./agui_events.js";

export interface StandardAgUiConsumerOptions {
  /** Pre-apply normalized events; snapshot still reflects earlier accepted events. Receives a copy. */
  onEvent?: (event: BaseEvent) => void | Promise<void>;
  /** After application/final status; awaited copies. A stalled callback permits at most
   * 128 queued canonical events plus one waiter, then consumption fails and unsubscribes. */
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
  private pendingEvents = 0;
  constructor(private readonly source: AgUiEventSource, private readonly binding: AgUiRunBinding,
    private readonly onApplied: () => void | Promise<void>, private readonly onOverflow: (error: Error) => void) {
    super({ threadId: binding.threadId, agentId: "zebra-standard-consumer", debug: false });
  }
  run(_input: RunAgentInput): Observable<BaseEvent> {
    const asyncSource = this.source as AsyncIterable<unknown>;
    const source = typeof asyncSource[Symbol.asyncIterator] !== "function" ? this.source : {
      [Symbol.asyncIterator]: () => {
        const iterator = asyncSource[Symbol.asyncIterator]();
        let returned: Promise<IteratorResult<unknown>> | undefined;
        const requestReturn = () => returned ??= Promise.resolve(iterator.return?.() ?? { done: true, value: undefined });
        // Request cleanup immediately even when next() awaits caller-owned IO. Such IO
        // cannot be forcibly cancelled; eventual RxJS cleanup reuses the same request.
        this.cleanup = () => { try { void requestReturn().catch(() => {}); } catch { /* preserve the consumer failure */ } };
        return { next: () => iterator.next(), return: requestReturn };
      },
    };
    return boundAgUiEvents(source, this.binding).pipe(takeUntil(this.stopped));
  }
  public abortRun(): void {
    this.stopped.next();
    this.stopped.complete();
    this.cleanup?.();
  }
  public waitForPreviousApplied(): Promise<void> { return this.previousApplied; }
  public dequeueEvent(): void { this.pendingEvents--; }
  protected apply(input: RunAgentInput, events: Observable<BaseEvent>, subscribers: AgentSubscriber[]) {
    // ponytail: reject beyond 128 queued canonical events (+1 notification waiter).
    // Pull-paced ingress is the upgrade; this reader cap is not a wire-profile limit.
    return super.apply(input, events.pipe(tap(() => {
      if (++this.pendingEvents > 128) {
        const error = new Error("AG-UI pending event limit (128) exceeded");
        this.onOverflow(error);
        throw error;
      }
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
 * cannot be forcibly cancelled. Ingress overflow rejects without awaiting those promises. */
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
    let hasStateSnapshot = false;
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
    }, failApplication);
    this.status = "consuming";
    try {
      await Promise.race([this.agent.runAgent({ runId: this.binding.runId }, {
        onEvent: async ({ event, messages, state }) => {
          this.agent!.dequeueEvent();
          try {
            await this.agent!.waitForPreviousApplied();
            if (applicationError) return { stopPropagation: true };
            // Upstream warns and skips failed patches. Preflight without replacing its reducer.
            if (event.type === "STATE_SNAPSHOT") hasStateSnapshot = true;
            if (event.type === "STATE_DELTA") {
              if (!hasStateSnapshot) throw new Error("STATE_DELTA has no accepted snapshot base");
              jsonpatch.applyPatch(state, (event as StateDeltaEvent).delta, true, false);
            }
            if (event.type === "ACTIVITY_DELTA") {
              const delta = event as ActivityDeltaEvent;
              const base = messages.find(m => m.id === delta.messageId);
              if (base?.role !== "activity") throw new Error("ACTIVITY_DELTA has no accepted activity base");
              jsonpatch.applyPatch(base.content, delta.patch, true, false);
            }
            await this.options.onEvent?.(structuredClone(event));
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
      await this.options.onSnapshot?.(this.snapshot);
      return this.snapshot;
    } catch (error) {
      this.status = "failed";
      throw error;
    }
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
