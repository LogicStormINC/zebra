import { enforceEvents, transformChunks, verifyEvents } from "@ag-ui/client";
import type { BaseEvent } from "@ag-ui/core";
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
