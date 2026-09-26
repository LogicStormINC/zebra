"use client";

import React, { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { AgentActivity, AgentArtifact, AgentMemorySetting, AgentMessage } from "@zebra-agent/ui-contracts";
import { AgentActivityGroup, type AgentActivityGroupProps } from "./agent-activity-group.tsx";
import { AgentApproval, AgentClarification, type AgentApprovalProps, type AgentClarificationProps } from "./agent-interrupts.tsx";
import { AgentMessageList, type AgentMessageListProps } from "./agent-message-list.tsx";
import { AgentArtifacts, AgentMemorySettings } from "./agent-resources.tsx";
import { AgentRunStatus, type AgentRunStatusProps } from "./agent-run-status.tsx";

export interface AgentChatProps {
  activities: readonly AgentActivity[];
  activityExpanded: boolean;
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
  messages: readonly AgentMessage[];
  onActivityExpandedChange: (expanded: boolean) => void;
  onArtifactOpen?: (id: string) => void;
  onMemoryToggle?: (id: string, enabled: boolean) => void;
  renderMessageContent?: AgentMessageListProps["renderContent"];
  runStatus?: AgentRunStatusProps;
  scrollKey?: string;
  theme?: "dark" | "light";
}

export function AgentChat(props: AgentChatProps) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const followsOutput = useRef(true);
  const [showLatest, setShowLatest] = useState(false);
  const empty = !props.messages.length && !props.activities.length;
  const terminalOutcome = props.runStatus?.state.phase === "terminal" ? props.runStatus.state.outcome : undefined;
  const terminalActivityStatus = terminalOutcome === "failed"
    ? "failed"
    : terminalOutcome === "blocked"
      ? "blocked"
    : terminalOutcome === "cancelled"
      ? "cancelled"
        : terminalOutcome
          ? "completed"
          : undefined;
  useEffect(() => {
    followsOutput.current = true;
    setShowLatest(false);
  }, [props.scrollKey]);
  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || !followsOutput.current) return;
    if (typeof viewport.scrollTo === "function") {
      viewport.scrollTo({ behavior: "auto", top: viewport.scrollHeight });
    }
  }, [props.activities, props.messages, props.runStatus?.state]);
  return (
    <section className={`zebra-agent-chat ${props.className ?? ""}`.trim()} data-theme={props.theme ?? "dark"}>
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
        {empty && props.emptyState ? <div className="zebra-agent-chat__empty">{props.emptyState}</div> : (
          <>
            <AgentMessageList labels={props.messageLabels} messages={props.messages} renderContent={props.renderMessageContent} />
            <AgentActivityGroup
              activities={props.activities}
              expanded={props.activityExpanded}
              labels={props.activityLabels}
              onExpandedChange={props.onActivityExpandedChange}
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
      {showLatest ? (
        <button
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
          {props.latestOutputLabel ?? "View latest output"}
        </button>
      ) : null}
      <div className="zebra-agent-chat__composer">{props.composer}</div>
    </section>
  );
}
