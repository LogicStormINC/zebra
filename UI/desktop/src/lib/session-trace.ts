import type { SessionEvent } from "../types";

export interface SessionToolTrace {
  toolName: string;
  status: string;
  arguments: Record<string, unknown>;
  output: string;
  metadata: Record<string, unknown>;
  policyDecision?: string;
}

export interface SessionAttemptTrace {
  attemptNumber: number;
  assistantMessage?: string;
  tools: SessionToolTrace[];
}

interface PendingAttempt {
  attemptNumber: number;
  assistantMessage?: string;
  pendingToolName?: string;
  pendingArguments: Record<string, unknown>;
  pendingPolicy: { decision?: string };
  tools: SessionToolTrace[];
}

function getAttempt(map: Map<number, PendingAttempt>, attemptNumber: number) {
  const current = map.get(attemptNumber);
  if (current) {
    return current;
  }
  const created: PendingAttempt = {
    attemptNumber,
    pendingArguments: {},
    pendingPolicy: {},
    tools: [],
  };
  map.set(attemptNumber, created);
  return created;
}

export function projectAttemptTrace(events: SessionEvent[]): SessionAttemptTrace[] {
  const attempts = new Map<number, PendingAttempt>();

  for (const event of events) {
    const attemptNumber = typeof event.payload.attempt_number === "number" ? event.payload.attempt_number : null;
    if (!attemptNumber || attemptNumber <= 0) {
      continue;
    }
    const attempt = getAttempt(attempts, attemptNumber);

    if (event.event_type === "model_response_received") {
      if (typeof event.payload.assistant_message === "string") {
        attempt.assistantMessage = event.payload.assistant_message;
      }
      continue;
    }

    if (event.event_type === "tool_call_proposed") {
      if (typeof event.payload.tool_name === "string") {
        attempt.pendingToolName = event.payload.tool_name;
      }
      if (typeof event.payload.arguments === "object" && event.payload.arguments && !Array.isArray(event.payload.arguments)) {
        attempt.pendingArguments = event.payload.arguments as Record<string, unknown>;
      }
      continue;
    }

    if (event.event_type === "policy_decision_made") {
      attempt.pendingPolicy = {
        decision: typeof event.payload.decision === "string" ? event.payload.decision : undefined,
      };
      continue;
    }

    if (event.event_type !== "tool_execution_completed" && event.event_type !== "tool_execution_failed") {
      continue;
    }

    if (typeof event.payload.tool_name !== "string" || typeof event.payload.status !== "string") {
      continue;
    }

    attempt.tools.push({
      toolName: event.payload.tool_name,
      status: event.payload.status,
      arguments:
        event.payload.tool_name === attempt.pendingToolName ? { ...attempt.pendingArguments } : {},
      output: typeof event.payload.output === "string" ? event.payload.output : "",
      metadata:
        typeof event.payload.metadata === "object" && event.payload.metadata && !Array.isArray(event.payload.metadata)
          ? (event.payload.metadata as Record<string, unknown>)
          : {},
      policyDecision: attempt.pendingPolicy.decision,
    });
    attempt.pendingToolName = undefined;
    attempt.pendingArguments = {};
    attempt.pendingPolicy = {};
  }

  return [...attempts.values()]
    .sort((left, right) => left.attemptNumber - right.attemptNumber)
    .map((attempt) => ({
      attemptNumber: attempt.attemptNumber,
      assistantMessage: attempt.assistantMessage,
      tools: attempt.tools,
    }));
}
