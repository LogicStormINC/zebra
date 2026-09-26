"use client";

import React from "react";
import type {
  AgentRecoveryAction,
  AgentRunOutcome,
  AgentRunPhase,
  AgentRunState,
} from "@zebra-agent/ui-contracts";

export interface AgentRunStatusLabels {
  actions: Record<AgentRecoveryAction, string>;
  diagnostic: (id: string) => string;
  outcomes: Record<AgentRunOutcome, string>;
  phases: Record<Exclude<AgentRunPhase, "queued" | "terminal">, string>;
  queued: (position?: number) => string;
}

export type AgentRunStatusLabelOverrides =
  Partial<Omit<AgentRunStatusLabels, "actions" | "outcomes" | "phases">> & {
    actions?: Partial<Record<AgentRecoveryAction, string>>;
    outcomes?: Partial<Record<AgentRunOutcome, string>>;
    phases?: Partial<Record<Exclude<AgentRunPhase, "queued" | "terminal">, string>>;
  };

export interface AgentRunStatusProps {
  className?: string;
  labels?: AgentRunStatusLabelOverrides;
  onReconnect?: () => void | Promise<void>;
  onResume?: () => void | Promise<void>;
  onRetry?: () => void | Promise<void>;
  state: AgentRunState;
}

const DEFAULT_LABELS: AgentRunStatusLabels = {
  actions: { reconnect: "Reconnect", resume: "Continue task", retry: "Retry original request" },
  diagnostic: (id) => `Diagnostic ID: ${id}`,
  outcomes: {
    blocked: "Blocked",
    cancelled: "Cancelled",
    completed: "Completed",
    failed: "Failed",
    partial: "Partially completed",
  },
  phases: {
    accepted: "Accepted by server",
    disconnected: "Connection interrupted",
    idle: "Ready",
    paused: "Paused",
    reconciling: "Checking the last operation",
    running: "Working",
    submitting: "Submitting locally",
    waiting_for_user: "Waiting for your input",
  },
  queued: (position) => position === undefined ? "Queued" : `Queued · position ${position}`,
};

export function AgentRunStatus(props: AgentRunStatusProps) {
  const labels = mergeLabels(props.labels);
  const { state } = props;
  const title = state.phase === "terminal"
    ? labels.outcomes[state.outcome]
    : state.phase === "queued"
      ? labels.queued(state.queuePosition)
      : labels.phases[state.phase];
  const actions = [...new Set(state.availableActions)].filter((action) => actionAllowed(action, state));
  const callbacks = { reconnect: props.onReconnect, resume: props.onResume, retry: props.onRetry };
  const tone = state.phase === "terminal" ? state.outcome : state.phase;

  return (
    <section
      className={`zebra-agent-run-status zebra-agent-run-status--${tone} ${props.className ?? ""}`.trim()}
    >
      <span aria-hidden="true" className="zebra-agent-run-status__marker" />
      <span aria-live="polite" className="zebra-agent-run-status__body" role="status">
        <strong>{title}</strong>
        {state.safeMessage ? <span>{state.safeMessage}</span> : null}
        {state.diagnosticId ? <code>{labels.diagnostic(state.diagnosticId)}</code> : null}
      </span>
      {actions.length ? (
        <span className="zebra-agent-run-status__actions">
          {actions.map((action) => (
            <button disabled={!callbacks[action]} key={action} onClick={() => void callbacks[action]?.()} type="button">
              {labels.actions[action]}
            </button>
          ))}
        </span>
      ) : null}
    </section>
  );
}

function mergeLabels(labels?: AgentRunStatusLabelOverrides): AgentRunStatusLabels {
  return {
    ...DEFAULT_LABELS,
    ...labels,
    actions: { ...DEFAULT_LABELS.actions, ...labels?.actions },
    outcomes: { ...DEFAULT_LABELS.outcomes, ...labels?.outcomes },
    phases: { ...DEFAULT_LABELS.phases, ...labels?.phases },
  };
}

function actionAllowed(action: AgentRecoveryAction, state: AgentRunState): boolean {
  if (state.phase === "reconciling") return false;
  if (action === "reconnect") return state.phase === "disconnected";
  if (action === "resume") {
    return state.phase === "paused" ||
      (state.phase === "terminal" && (state.outcome === "partial" || state.outcome === "blocked"));
  }
  return state.phase === "terminal" && state.outcome !== "completed";
}
