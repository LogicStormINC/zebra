"use client";

import React, { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import type {
  AgentActivityStatus,
  AgentConversationTurn,
  AgentTurnStatus,
  AgentWorkSegment,
} from "@zebra-agent/ui-contracts";
import { AgentActivityGroup, type AgentActivityGroupProps } from "./agent-activity-group.tsx";
import {
  AgentMessageItem,
  resolveAgentMessageLabels,
  type AgentMessageListProps,
} from "./agent-message-list.tsx";
import { AgentArtifacts } from "./agent-resources.tsx";

export interface AgentConversationTimelineProps {
  activityLabels?: AgentActivityGroupProps["labels"];
  className?: string;
  messageLabels?: AgentMessageListProps["labels"];
  onArtifactOpen?: (id: string) => void;
  renderMessageContent?: AgentMessageListProps["renderContent"];
  renderTurnFooter?: (turn: AgentConversationTurn) => ReactNode;
  turns: readonly AgentConversationTurn[];
}

export function AgentConversationTimeline(props: AgentConversationTimelineProps) {
  const labels = resolveAgentMessageLabels(props.messageLabels);
  return (
    <ol className={`zebra-agent-timeline ${props.className ?? ""}`.trim()}>
      {props.turns.map((turn) => (
        <li
          className={`zebra-agent-turn zebra-agent-turn--${turn.status}`}
          data-live-turn={isLiveTurn(turn.status) ? "true" : "false"}
          key={turn.id}
        >
          <div className="zebra-agent-turn__body">
            {turn.userMessage ? (
              <ol className="zebra-agent-message-list zebra-agent-turn__messages">
                <AgentMessageItem
                  labels={labels}
                  message={turn.userMessage}
                  renderContent={props.renderMessageContent}
                />
              </ol>
            ) : null}
            {turn.workSegments.map((segment) => (
              <AgentTurnWork
                activityLabels={props.activityLabels}
                key={segment.id}
                segment={segment}
                turnStatus={turn.status}
              />
            ))}
            {turn.assistantMessage ? (
              <ol className="zebra-agent-message-list zebra-agent-turn__messages">
                <AgentMessageItem
                  labels={labels}
                  message={turn.assistantMessage}
                  renderContent={props.renderMessageContent}
                />
              </ol>
            ) : null}
            {turn.artifacts?.length ? (
              <AgentArtifacts artifacts={turn.artifacts} onOpen={props.onArtifactOpen} />
            ) : null}
            {props.renderTurnFooter ? props.renderTurnFooter(turn) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

function AgentTurnWork({
  activityLabels,
  segment,
  turnStatus,
}: {
  activityLabels?: AgentActivityGroupProps["labels"];
  segment: AgentWorkSegment;
  turnStatus: AgentTurnStatus;
}) {
  const active = isLiveTurn(turnStatus);
  const terminalStatus = toActivityTerminalStatus(turnStatus);
  const diagnostic = terminalStatus === "failed" || terminalStatus === "blocked";
  const [expanded, setExpanded] = useState(active || diagnostic);
  const previousStatus = useRef(turnStatus);
  useEffect(() => {
    if (previousStatus.current !== turnStatus) {
      if (active || diagnostic) setExpanded(true);
      else if (terminalStatus) setExpanded(false);
      previousStatus.current = turnStatus;
    }
  }, [active, diagnostic, terminalStatus, turnStatus]);
  const labels = useMemo(
    () => segment.label
      ? { ...activityLabels, summary: () => segment.label as string }
      : activityLabels,
    [activityLabels, segment.label],
  );
  if (!segment.activities.length) return null;
  return (
    <AgentActivityGroup
      activities={segment.activities}
      className="zebra-agent-turn__work"
      expanded={expanded}
      labels={labels}
      onExpandedChange={setExpanded}
      terminalStatus={terminalStatus}
    />
  );
}

function isLiveTurn(status: AgentTurnStatus) {
  return status === "queued" || status === "running" || status === "waiting";
}

function toActivityTerminalStatus(
  status: AgentTurnStatus,
): Exclude<AgentActivityStatus, "running" | "ready"> | undefined {
  if (status === "completed" || status === "partial") return "completed";
  if (status === "failed" || status === "blocked" || status === "cancelled") return status;
  return undefined;
}
