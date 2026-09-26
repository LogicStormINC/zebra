"use client";

import React, { type ReactNode, useLayoutEffect, useRef, useState } from "react";
import type { AgentActivity, AgentArtifact, AgentConversationTurn, AgentMemorySetting, AgentMessage } from "@zebra-agent/ui-contracts";
import { AgentActivityGroup, type AgentActivityGroupProps } from "./agent-activity-group.tsx";
import { AgentConversationTimeline, type AgentConversationTimelineProps } from "./agent-conversation-timeline.tsx";
import { AgentApproval, AgentClarification, type AgentApprovalProps, type AgentClarificationProps } from "./agent-interrupts.tsx";
import { AgentMessageList, type AgentMessageListProps } from "./agent-message-list.tsx";
import { AgentArtifacts, AgentMemorySettings } from "./agent-resources.tsx";
import { AgentRunStatus, type AgentRunStatusProps } from "./agent-run-status.tsx";
import { createAgentThemeStyle, type AgentThemeTokens } from "../theme.ts";

export interface AgentChatProps {
  activities?: readonly AgentActivity[];
  activityExpanded?: boolean;
  activityLabels?: AgentActivityGroupProps["labels"];
  approval?: AgentApprovalProps;
  artifacts?: readonly AgentArtifact[];
  className?: string;
  clarification?: AgentClarificationProps;
  composer: ReactNode;
  emptyState?: ReactNode;
  header?: ReactNode;
  memorySettings?: readonly AgentMemorySetting[];
  latestOutputLabel?: string;
  messageLabels?: AgentMessageListProps["labels"];
  messages?: readonly AgentMessage[];
  onActivityExpandedChange?: (expanded: boolean) => void;
  onArtifactOpen?: (id: string) => void;
  onMemoryToggle?: (id: string, enabled: boolean) => void;
  renderMessageContent?: AgentMessageListProps["renderContent"];
  renderTurnFooter?: AgentConversationTimelineProps["renderTurnFooter"];
  runStatus?: AgentRunStatusProps;
  scrollKey?: string;
  theme?: "dark" | "light";
  themeTokens?: Partial<AgentThemeTokens>;
  turns?: readonly AgentConversationTurn[];
}

const scrollPositions = new Map<string, number>();
const maximumRememberedScrollPositions = 100;

export function AgentChat(props: AgentChatProps) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const followsOutput = useRef(true);
  const [showLatest, setShowLatest] = useState(false);
  const messages = props.messages ?? [];
  const activities = props.activities ?? [];
  const empty = props.turns ? !props.turns.length : !messages.length && !activities.length;
  const runState = props.runStatus?.state;
  const runStatusSignature = runState
    ? `${runState.phase}:${runState.phase === "terminal" ? runState.outcome : ""}:${runState.queuePosition ?? ""}:${runState.safeMessage ?? ""}`
    : "";
  const terminalOutcome = runState?.phase === "terminal" ? runState.outcome : undefined;
  const terminalActivityStatus = terminalOutcome === "failed"
    ? "failed"
    : terminalOutcome === "blocked"
      ? "blocked"
    : terminalOutcome === "cancelled"
      ? "cancelled"
        : terminalOutcome
          ? "completed"
          : undefined;
  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    followsOutput.current = true;
    setShowLatest(false);
    const key = props.scrollKey;
    const saved = key ? scrollPositions.get(key) : undefined;
    viewport.scrollTop = saved ?? viewport.scrollHeight;
    return () => {
      if (key) rememberScrollPosition(key, viewport.scrollTop);
    };
  }, [props.scrollKey]);
  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || !followsOutput.current) return;
    if (typeof viewport.scrollTo === "function") {
      viewport.scrollTo({ behavior: "auto", top: viewport.scrollHeight });
    }
  }, [props.activities, props.messages, runStatusSignature, props.turns]);
  return (
    <section
      className={`zebra-agent-chat ${empty ? "zebra-agent-chat--empty" : ""} ${props.header ? "" : "zebra-agent-chat--headerless"} ${props.className ?? ""}`.trim()}
      data-theme={props.theme ?? "dark"}
      style={createAgentThemeStyle(props.themeTokens)}
    >
      {props.header ? <header className="zebra-agent-chat__header">{props.header}</header> : null}
      <div
        className="zebra-agent-chat__viewport"
        onScroll={(event) => {
          const viewport = event.currentTarget;
          followsOutput.current = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 48;
          setShowLatest(!followsOutput.current);
        }}
        ref={viewportRef}
      >
        <div className="zebra-agent-chat__stage">
          <div className="zebra-agent-chat__content">
            {empty && props.emptyState ? (
              <div className="zebra-agent-chat__empty">{props.emptyState}</div>
            ) : props.turns ? (
              <AgentConversationTimeline
                {...(props.activityLabels ? { activityLabels: props.activityLabels } : {})}
                {...(props.messageLabels ? { messageLabels: props.messageLabels } : {})}
                {...(props.onArtifactOpen ? { onArtifactOpen: props.onArtifactOpen } : {})}
                {...(props.renderMessageContent ? { renderMessageContent: props.renderMessageContent } : {})}
                {...(props.renderTurnFooter ? { renderTurnFooter: props.renderTurnFooter } : {})}
                turns={props.turns}
              />
            ) : (
              <>
                <AgentMessageList labels={props.messageLabels} messages={messages} renderContent={props.renderMessageContent} />
                <AgentActivityGroup
                  activities={activities}
                  expanded={props.activityExpanded ?? false}
                  labels={props.activityLabels}
                  onExpandedChange={props.onActivityExpandedChange ?? (() => undefined)}
                  terminalStatus={terminalActivityStatus}
                />
              </>
            )}
            {props.runStatus ? <AgentRunStatus {...props.runStatus} /> : null}
            {props.approval ? <AgentApproval {...props.approval} /> : null}
            {props.clarification ? <AgentClarification {...props.clarification} /> : null}
            {props.artifacts ? <AgentArtifacts artifacts={props.artifacts} onOpen={props.onArtifactOpen} /> : null}
            {props.memorySettings ? <AgentMemorySettings onToggle={props.onMemoryToggle} settings={props.memorySettings} /> : null}
          </div>
          <div className="zebra-agent-chat__composer">{props.composer}</div>
        </div>
      </div>
      {showLatest ? (
        <button
          aria-label={props.latestOutputLabel ?? "View latest output"}
          className="zebra-agent-chat__latest"
          onClick={() => {
            followsOutput.current = true;
            setShowLatest(false);
            const viewport = viewportRef.current;
            if (viewport && typeof viewport.scrollTo === "function") {
              viewport.scrollTo({ behavior: "auto", top: viewport.scrollHeight });
            }
          }}
          type="button"
        >
          <span aria-hidden="true">↓</span>
        </button>
      ) : null}
    </section>
  );
}

function rememberScrollPosition(key: string, top: number) {
  scrollPositions.delete(key);
  scrollPositions.set(key, top);
  if (scrollPositions.size > maximumRememberedScrollPositions) {
    const oldest = scrollPositions.keys().next().value;
    if (oldest) scrollPositions.delete(oldest);
  }
}
