"use client";

import React, { useEffect, useRef } from "react";
import type { AgentActivity, AgentActivityStatus } from "@zebra-agent/ui-contracts";

export interface AgentActivityGroupLabels {
  blocked: string;
  cancelled: string;
  completed: string;
  failed: string;
  ready: string;
  running: string;
  summary: (count: number) => string;
}

export interface AgentActivityGroupProps {
  activities: readonly AgentActivity[];
  className?: string;
  expanded: boolean;
  labels?: Partial<AgentActivityGroupLabels> | undefined;
  onExpandedChange: (expanded: boolean) => void;
  terminalStatus?: Exclude<AgentActivityStatus, "running" | "ready"> | undefined;
}

const DEFAULT_LABELS: AgentActivityGroupLabels = {
  blocked: "Blocked",
  cancelled: "Cancelled",
  completed: "Completed",
  failed: "Failed",
  ready: "Ready",
  running: "Running",
  summary: (count) => `Work log · ${count}`,
};

export function AgentActivityGroup(props: AgentActivityGroupProps) {
  const labels = { ...DEFAULT_LABELS, ...props.labels };
  const active = !props.terminalStatus && props.activities.some((item) => item.status === "running");
  const wasActive = useRef(active);
  useEffect(() => {
    const shouldCollapse = props.terminalStatus === "completed" || props.terminalStatus === "cancelled";
    if (wasActive.current && !active && shouldCollapse && props.expanded) {
      props.onExpandedChange(false);
    }
    wasActive.current = active;
  }, [active, props.expanded, props.onExpandedChange, props.terminalStatus]);
  if (!props.activities.length) return null;
  const open = active || props.expanded;
  const activityKind = props.activities[0]?.kind ?? "tool";
  const terminal = props.terminalStatus !== undefined;
  return (
    <details
      className={`zebra-agent-activity ${active ? "zebra-agent-activity--active" : ""} ${terminal ? "zebra-agent-activity--terminal" : ""} ${props.className ?? ""}`.trim()}
      data-activity-kind={activityKind}
      onToggle={(event) => {
        if (!active) props.onExpandedChange(event.currentTarget.open);
      }}
      open={open}
    >
      <summary>
        <span aria-hidden="true" className="zebra-agent-activity__summary-icon" />
        <strong className="zebra-agent-activity__summary-label">{labels.summary(props.activities.length)}</strong>
        <span aria-hidden="true" className="zebra-agent-activity__summary-separator">·</span>
        <span className="zebra-agent-activity__summary-status">
          {active ? labels.running : props.terminalStatus ? labels[props.terminalStatus] : latestStatus(props.activities, labels)}
        </span>
        <span aria-hidden="true" className="zebra-agent-activity__summary-chevron">›</span>
      </summary>
      <ol>
        {props.activities.map((item) => (
          <li
            className={`zebra-agent-activity__item zebra-agent-activity__item--${item.status}`}
            data-activity-kind={item.kind}
            key={item.activityId}
          >
            <span aria-hidden="true" className="zebra-agent-activity__marker" />
            <span className="zebra-agent-activity__body">
              <strong>{item.title}</strong>
              {item.description ? <span>{item.description}</span> : null}
            </span>
            <span className="zebra-agent-activity__status">
              {durationLabel(item.durationMs)}{item.durationMs ? " · " : ""}{labels[item.status]}
            </span>
          </li>
        ))}
      </ol>
    </details>
  );
}

function durationLabel(durationMs?: number) {
  if (durationMs === undefined) return "";
  if (durationMs < 1_000) return `${Math.max(1, Math.round(durationMs))}ms`;
  return `${Math.round(durationMs / 100) / 10}s`;
}

function latestStatus(activities: readonly AgentActivity[], labels: AgentActivityGroupLabels) {
  const status: AgentActivityStatus = activities.at(-1)?.status ?? "ready";
  return labels[status];
}
