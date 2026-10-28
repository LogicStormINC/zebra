import { enforceEvents, transformChunks, verifyEvents } from "@ag-ui/client";
import type { ActivityDeltaEvent, BaseEvent, Message, State, StateDeltaEvent } from "@ag-ui/core";
import jsonpatch from "fast-json-patch";
import { defer, from, map, type Observable } from "rxjs";

/** Scope supplied by the caller's authorized stream, never inferred from events. */
export interface AgUiRunBinding { threadId: string; runId: string }
export type AgUiEventSource = Iterable<unknown> | AsyncIterable<unknown>;

export function assertAgUiBinding(actual: { threadId?: string | undefined; runId?: string | undefined }, expected: AgUiRunBinding): void {
  if ((actual.threadId !== undefined && actual.threadId !== expected.threadId) ||
      (actual.runId !== undefined && actual.runId !== expected.runId)) {
    throw new Error("AG-UI event binding does not match the consumer thread/run");
  }
}

/** Internal boundary shared with the official AbstractAgent pipeline. */
export function boundAgUiEvents(source: AgUiEventSource, binding: AgUiRunBinding): Observable<BaseEvent> {
  const expected = { ...binding };
  if (typeof expected.threadId !== "string" || typeof expected.runId !== "string") {
    throw new Error("AG-UI binding requires threadId and runId strings");
  }
  return defer(() => {
    let started = false;
    return from(source).pipe(
      map(value => {
        if (!value || typeof value !== "object" || typeof (value as BaseEvent).type !== "string") {
          throw new Error("AG-UI event requires a type discriminator");
        }
        const json = JSON.stringify(value);
        if (json.length > 2_097_152 || new TextEncoder().encode(json).byteLength > 2_097_152) {
          throw new Error("AG-UI canonical event exceeds byte budget");
        }
        return structuredClone(value) as BaseEvent;
      }),
      enforceEvents(),
      map(event => {
        assertAgUiBinding({ threadId: event.threadId as string | undefined, runId: event.runId as string | undefined }, expected);
        if (event.type === "RUN_STARTED") {
          if (started) throw new Error("A bound consumer accepts only one RUN_STARTED");
          started = true;
          if (event.input && typeof event.input === "object") assertAgUiBinding(event.input, expected);
        }
        return event;
      }),
    );
  });
}

/** Official canonical pipeline; malformed known events fail, unknown material is stripped/dropped. */
export function standardAgUiEvents(source: AgUiEventSource, binding: AgUiRunBinding): Observable<BaseEvent> {
  return defer(() => boundAgUiEvents(source, binding).pipe(transformChunks(), verifyEvents()));
}

/** Preflight only: the official reducer still owns all mutations. */
export function validateAgUiPatch(event: BaseEvent, messages: readonly Readonly<Message>[], state: State, hasSnapshot: boolean): boolean {
  if (event.type === "STATE_SNAPSHOT") hasSnapshot = true;
  if (event.type === "STATE_DELTA") {
    if (!hasSnapshot) throw new Error("STATE_DELTA has no accepted snapshot base");
    jsonpatch.applyPatch(state, (event as StateDeltaEvent).delta, true, false);
  }
  if (event.type === "ACTIVITY_DELTA") {
    const delta = event as ActivityDeltaEvent;
    const base = messages.find(m => m.id === delta.messageId);
    if (base?.role !== "activity") throw new Error("ACTIVITY_DELTA has no accepted activity base");
    jsonpatch.applyPatch(base.content, delta.patch, true, false);
  }
  return hasSnapshot;
}
