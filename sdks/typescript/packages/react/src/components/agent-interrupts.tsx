"use client";

import React, { useId } from "react";
import type { ApprovalRequestWire, ClarificationRequestWire } from "../hitl/index.ts";

export interface AgentApprovalProps {
  approval: ApprovalRequestWire;
  className?: string;
  disabled?: boolean;
  labels?: Partial<{ approve: string; reject: string; requested: string }>;
  onDecision: (decision: "approve" | "reject") => void | Promise<void>;
}

export function AgentApproval(props: AgentApprovalProps) {
  const id = useId();
  const labels = { approve: "Approve", reject: "Reject", requested: "Approval required", ...props.labels };
  return (
    <section aria-labelledby={`approval-${id}`} className={`zebra-agent-interrupt ${props.className ?? ""}`.trim()}>
      <span className="zebra-agent-interrupt__eyebrow">{labels.requested}</span>
      <h3 id={`approval-${id}`}>{props.approval.tool_name}</h3>
      <p>{props.approval.reason}</p>
      <div className="zebra-agent-interrupt__actions">
        <button disabled={props.disabled} onClick={() => void props.onDecision("reject")} type="button">{labels.reject}</button>
        <button className="zebra-agent-interrupt__primary" disabled={props.disabled} onClick={() => void props.onDecision("approve")} type="button">{labels.approve}</button>
      </div>
    </section>
  );
}

export interface AgentClarificationProps {
  clarification: ClarificationRequestWire;
  className?: string;
  disabled?: boolean;
  labels?: Partial<{ requested: string }>;
  onRespond: (choice: string) => void | Promise<void>;
}

export function AgentClarification(props: AgentClarificationProps) {
  const id = useId();
  const labels = { requested: "Input required", ...props.labels };
  return (
    <section aria-labelledby={`clarification-${id}`} className={`zebra-agent-interrupt ${props.className ?? ""}`.trim()}>
      <span className="zebra-agent-interrupt__eyebrow">{labels.requested}</span>
      <h3 id={`clarification-${id}`}>{props.clarification.question}</h3>
      <div className="zebra-agent-interrupt__choices">
        {props.clarification.choices.map((choice) => (
          <button disabled={props.disabled} key={choice} onClick={() => void props.onRespond(choice)} type="button">{choice}</button>
        ))}
      </div>
    </section>
  );
}
