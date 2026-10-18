"use client";

import React, { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import type {
  AgentConversationTurn,
  AgentConversationItem,
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
import { AgentRunStatus, type AgentRunStatusProps } from "./agent-run-status.tsx";
import { selectConversationItems } from "./conversation-items.ts";
import { AgentConversationAnnouncement } from "./conversation-announcement.tsx";

export interface AgentConversationTimelineProps {
  /** Fold execution details when the Host begins delivering the answer. */
  collapseWork?: boolean | undefined;
  /** Host-identified progress messages, grouped with tools rather than answer text. */
  workMessageIds?: readonly string[] | undefined;
  activityLabels?: AgentActivityGroupProps["labels"];
  className?: string;
  contentRenderer?: AgentMessageListProps["contentRenderer"];
  messageLabels?: AgentMessageListProps["labels"];
  onArtifactOpen?: (id: string) => void;
  renderMessageContent?: AgentMessageListProps["renderContent"];
  renderTurnFooter?: (turn: AgentConversationTurn) => ReactNode;
  runStatusLabels?: AgentRunStatusProps["labels"];
  scrollKey?: string;
  turns: readonly AgentConversationTurn[];
}

export function AgentConversationTimeline(props: AgentConversationTimelineProps) {
  const labels = resolveAgentMessageLabels(props.messageLabels);
  const turns = useMemo(() => props.turns.map((turn) => ({ turn, items: selectConversationItems(turn) })), [props.turns]);
  return (
    <>
      <ol className={`zebra-agent-timeline ${props.className ?? ""}`.trim()}>
        {turns.map(({ turn, items }) => {
          const hasTerminalStatus = items.some((item) => item.kind === "status" &&
            item.state.phase === "terminal" && item.state.outcome === turn.status);
          return (
            <li
              className={`zebra-agent-turn zebra-agent-turn--${turn.status}`}
              data-live-turn={isLiveTurn(turn.status) ? "true" : "false"}
              key={turn.id}
            >
              <div className="zebra-agent-turn__body">
                {turn.userMessage ? (
                  <ol className="zebra-agent-message-list zebra-agent-turn__messages">
                    <AgentMessageItem
                      contentRenderer={props.contentRenderer}
                      labels={labels}
                      message={turn.userMessage}
                      renderContent={props.renderMessageContent}
                    />
                  </ol>
                ) : null}
                {groupWorkItems(items, props.workMessageIds).flatMap((group) => {
                  const content = group.items.map((item) => (
                  <React.Fragment key={item.kind === "message" ? `message:${item.message.id}` : `${item.kind}:${item.id}`}>
                    {item.kind === "message" ? (
                      <ol className="zebra-agent-message-list zebra-agent-turn__messages">
                        <AgentMessageItem
                          contentRenderer={props.contentRenderer}
                          labels={labels}
                          message={item.message}
                          renderContent={props.renderMessageContent}
                        />
                      </ol>
                    ) : item.kind === "activity" ? (
                      <AgentTurnWork activityLabels={props.activityLabels} collapseWork={props.collapseWork} segment={item.segment} turnStatus={turn.status} />
                    ) : (
                      <AgentRunStatus {...(props.runStatusLabels ? { labels: props.runStatusLabels } : {})} state={item.state} />
                    )}
                  </React.Fragment>
                  ));
                  return group.work ? [<AgentTurnProgress key={`progress:${group.items[0]!.id}`}
                    collapseWork={props.collapseWork} turnStatus={turn.status} activityLabels={props.activityLabels}
                    count={group.items.length}>{content}</AgentTurnProgress>] : content;
                })}
                {turn.artifacts?.length ? (
                  <AgentArtifacts artifacts={turn.artifacts} onOpen={props.onArtifactOpen} />
                ) : null}
                {!hasTerminalStatus && (turn.status === "partial" || turn.status === "failed" || turn.status === "blocked" || turn.status === "cancelled") ? (
                  <AgentRunStatus
                    {...(props.runStatusLabels ? { labels: props.runStatusLabels } : {})}
                    state={{ phase: "terminal", outcome: turn.status, availableActions: [] }}
                  />
                ) : null}
                {props.renderTurnFooter ? props.renderTurnFooter(turn) : null}
              </div>
            </li>
          );
        })}
      </ol>
      <AgentConversationAnnouncement scrollKey={props.scrollKey} turns={turns} />
    </>
  );
}

function groupWorkItems(items: readonly AgentConversationItem[], messageIds?: readonly string[]) {
  const ids = new Set(messageIds);
  const groups: { work: boolean; items: AgentConversationItem[] }[] = [];
  for (const item of items) {
    const work = messageIds !== undefined && (item.kind === "activity" ||
      (item.kind === "message" && ids.has(item.message.id)) || (item.kind === "status" && item.state.phase !== "terminal"));
    const previous = groups.at(-1);
    if (work && previous?.work) previous.items.push(item);
    else groups.push({ work, items: [item] });
  }
  return groups;
}

function AgentTurnProgress({ children, collapseWork, turnStatus, activityLabels, count }: {
  children: ReactNode; collapseWork?: boolean | undefined; turnStatus: AgentTurnStatus;
  activityLabels: AgentActivityGroupProps["labels"]; count: number;
}) {
  const live = isLiveTurn(turnStatus);
  const [expanded, setExpanded] = useState(live && !collapseWork);
  useEffect(() => { setExpanded(live && !collapseWork); }, [live, collapseWork]);
  return <details className="zebra-agent-activity zebra-agent-turn__progress" open={expanded}
    onToggle={(event) => { if (event.target === event.currentTarget && event.currentTarget.open !== expanded) setExpanded(event.currentTarget.open); }}>
    <summary>
      <span aria-hidden="true" className="zebra-agent-activity__summary-icon" />
      <strong className="zebra-agent-activity__summary-label">{activityLabels?.summary?.(count) ?? `Execution process · ${count}`}</strong>
      <span className="zebra-agent-activity__summary-status">{turnStatus === "waiting" ? activityLabels?.waiting ?? "Waiting for input" : live ? activityLabels?.running ?? "Running" :
        activityLabels?.[toActivityTerminalStatus(turnStatus) ?? "completed"] ?? turnStatus}</span>
      <span aria-hidden="true" className="zebra-agent-activity__summary-chevron">›</span>
    </summary>
    <div className="zebra-agent-turn__progress-content">{children}</div>
  </details>;
}

function AgentTurnWork({
  activityLabels,
  collapseWork = false,
  segment,
  turnStatus,
}: {
  activityLabels?: AgentActivityGroupProps["labels"];
  collapseWork?: boolean | undefined;
  segment: AgentWorkSegment;
  turnStatus: AgentTurnStatus;
}) {
  const active = isLiveTurn(turnStatus);
  const terminalStatus = toActivityTerminalStatus(turnStatus);
  const diagnostic = terminalStatus === "failed" || terminalStatus === "blocked" || terminalStatus === "partial" ||
    segment.activities.some((item) => item.status === "failed");
  const [expanded, setExpanded] = useState(!collapseWork && (active || diagnostic));
  const previousStatus = useRef(turnStatus);
  useEffect(() => {
    if (collapseWork) { setExpanded(false); previousStatus.current = turnStatus; return; }
    if (previousStatus.current !== turnStatus || diagnostic) {
      if (active || diagnostic) setExpanded(true);
      else if (terminalStatus) setExpanded(false);
      previousStatus.current = turnStatus;
    }
  }, [active, collapseWork, diagnostic, terminalStatus, turnStatus]);
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
      running={turnStatus === "running"}
      waiting={turnStatus === "waiting"}
    />
  );
}

function isLiveTurn(status: AgentTurnStatus) {
  return status === "queued" || status === "running" || status === "waiting";
}

function toActivityTerminalStatus(status: AgentTurnStatus) {
  if (status === "completed" || status === "partial" || status === "failed" || status === "blocked" || status === "cancelled") return status;
  return undefined;
}
