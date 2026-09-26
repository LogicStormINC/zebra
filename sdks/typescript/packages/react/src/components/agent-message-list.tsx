"use client";

import React, { type ReactNode } from "react";
import type { AgentMessage } from "@zebra-agent/ui-contracts";

export interface AgentMessageListLabels {
  assistant: string;
  empty: string;
  failed: string;
  sending: string;
  streaming: string;
  system: string;
  user: string;
}

export interface AgentMessageListProps {
  className?: string;
  labels?: Partial<AgentMessageListLabels> | undefined;
  messages: readonly AgentMessage[];
  renderContent?: ((message: AgentMessage) => ReactNode) | undefined;
}

const DEFAULT_LABELS: AgentMessageListLabels = {
  assistant: "Agent",
  empty: "No messages yet",
  failed: "Failed",
  sending: "Sending",
  streaming: "Responding",
  system: "System",
  user: "You",
};

export function AgentMessageList(props: AgentMessageListProps) {
  const labels = { ...DEFAULT_LABELS, ...props.labels };
  if (!props.messages.length) {
    return <div className={`zebra-agent-message-list zebra-agent-message-list--empty ${props.className ?? ""}`.trim()}>{labels.empty}</div>;
  }
  return (
    <ol aria-live="polite" aria-relevant="additions text" className={`zebra-agent-message-list ${props.className ?? ""}`.trim()} role="log">
      {props.messages.map((message) => (
        <li className={`zebra-agent-message zebra-agent-message--${message.role}`} key={message.id}>
          <article>
            <header className="zebra-agent-message__meta">
              <strong>{labels[message.role]}</strong>
              {message.timestampLabel ? <time>{message.timestampLabel}</time> : null}
              {message.status !== "complete" ? (
                <span className={`zebra-agent-message__status zebra-agent-message__status--${message.status}`}>
                  {labels[message.status]}
                </span>
              ) : null}
            </header>
            <div className="zebra-agent-message__content">
              {props.renderContent ? props.renderContent(message) : message.content}
            </div>
          </article>
        </li>
      ))}
    </ol>
  );
}
