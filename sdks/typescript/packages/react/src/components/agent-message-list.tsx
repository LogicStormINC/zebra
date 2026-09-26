"use client";

import React, { type ReactNode, useEffect, useRef, useState } from "react";
import type { AgentMessage } from "@zebra-agent/ui-contracts";

export interface AgentMessageListLabels {
  assistant: string;
  collapse: string;
  empty: string;
  expand: string;
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

interface AgentMessageItemProps {
  labels: AgentMessageListLabels;
  message: AgentMessage;
  renderContent?: AgentMessageListProps["renderContent"];
}

const DEFAULT_LABELS: AgentMessageListLabels = {
  assistant: "Agent",
  collapse: "Collapse message",
  empty: "No messages yet",
  expand: "Expand message",
  failed: "Failed",
  sending: "Sending",
  streaming: "Responding",
  system: "System",
  user: "You",
};

export function AgentMessageList(props: AgentMessageListProps) {
  const labels = resolveAgentMessageLabels(props.labels);
  if (!props.messages.length) {
    return <div className={`zebra-agent-message-list zebra-agent-message-list--empty ${props.className ?? ""}`.trim()}>{labels.empty}</div>;
  }
  return (
    <ol aria-live="polite" aria-relevant="additions text" className={`zebra-agent-message-list ${props.className ?? ""}`.trim()} role="log">
      {props.messages.map((message) => (
        <AgentMessageItem key={message.id} labels={labels} message={message} renderContent={props.renderContent} />
      ))}
    </ol>
  );
}

export function AgentMessageItem(props: AgentMessageItemProps) {
  const { labels, message } = props;
  const showMeta = Boolean(labels[message.role] || message.timestampLabel || message.status !== "complete");
  return (
    <li className={`zebra-agent-message zebra-agent-message--${message.role}`}>
      <article>
        {showMeta ? (
          <header className="zebra-agent-message__meta">
            {labels[message.role] ? <strong>{labels[message.role]}</strong> : null}
            {message.timestampLabel ? <time>{message.timestampLabel}</time> : null}
            {message.status !== "complete" ? (
              <span className={`zebra-agent-message__status zebra-agent-message__status--${message.status}`}>
                {labels[message.status]}
              </span>
            ) : null}
          </header>
        ) : null}
        {message.role === "user" ? (
          <AgentUserMessageBody contentKey={`${message.id}:${message.content}`} labels={labels}>
            {props.renderContent ? props.renderContent(message) : message.content}
          </AgentUserMessageBody>
        ) : (
          <div className="zebra-agent-message__content">
            {props.renderContent ? props.renderContent(message) : message.content}
          </div>
        )}
      </article>
    </li>
  );
}

const collapsedUserMessageHeight = 120;

function AgentUserMessageBody({
  children,
  contentKey,
  labels,
}: {
  children: ReactNode;
  contentKey: string;
  labels: AgentMessageListLabels;
}) {
  const contentRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [expandable, setExpandable] = useState(false);
  const [contentHeight, setContentHeight] = useState(collapsedUserMessageHeight);

  useEffect(() => {
    setExpanded(false);
  }, [contentKey]);
  useEffect(() => {
    const content = contentRef.current;
    if (!content) return;
    const measure = () => {
      setContentHeight(content.scrollHeight);
      setExpandable(content.scrollHeight > collapsedUserMessageHeight + 1);
    };
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(content);
    return () => observer.disconnect();
  }, [children, contentKey]);

  const label = expanded ? labels.collapse : labels.expand;
  return (
    <div className="zebra-agent-user-input">
      <div
        className={`zebra-agent-message__content zebra-agent-user-input__content ${expandable && !expanded ? "zebra-agent-user-input__content--clamped" : ""}`.trim()}
        data-expanded={expanded ? "true" : "false"}
        ref={contentRef}
        style={{ maxHeight: `${expanded ? Math.max(contentHeight, collapsedUserMessageHeight) : collapsedUserMessageHeight}px` }}
      >
        {children}
      </div>
      {expandable ? (
        <button
          aria-expanded={expanded}
          aria-label={label}
          className="zebra-agent-user-input__toggle"
          onClick={() => setExpanded((value) => !value)}
          title={label}
          type="button"
        >
          <span aria-hidden="true">{expanded ? "↑" : "↓"}</span>
        </button>
      ) : null}
    </div>
  );
}

export function resolveAgentMessageLabels(labels?: Partial<AgentMessageListLabels>) {
  return { ...DEFAULT_LABELS, ...labels };
}
