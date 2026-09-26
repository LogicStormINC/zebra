"use client";

import React from "react";
import type { AgentArtifact, AgentMemorySetting } from "@zebra-agent/ui-contracts";

export interface AgentArtifactsProps {
  artifacts: readonly AgentArtifact[];
  className?: string;
  labels?: Partial<{ empty: string; failed: string; open: string; processing: string; ready: string; title: string }>;
  onOpen?: ((id: string) => void) | undefined;
}

export function AgentArtifacts(props: AgentArtifactsProps) {
  const labels = { empty: "No artifacts", failed: "Failed", open: "Open", processing: "Processing", ready: "Ready", title: "Artifacts", ...props.labels };
  return (
    <section className={`zebra-agent-resources ${props.className ?? ""}`.trim()}>
      <h3>{labels.title}</h3>
      {!props.artifacts.length ? <p className="zebra-agent-resources__empty">{labels.empty}</p> : (
        <ul>{props.artifacts.map((artifact) => (
          <li key={artifact.id}>
            <span className="zebra-agent-resources__kind">{artifact.kind}</span>
            <span className="zebra-agent-resources__main"><strong>{artifact.name}</strong>{artifact.metadataLabel ? <small>{artifact.metadataLabel}</small> : null}</span>
            <span className={`zebra-agent-resources__status zebra-agent-resources__status--${artifact.status}`}>{labels[artifact.status]}</span>
            <button disabled={artifact.status !== "ready" || !props.onOpen} onClick={() => props.onOpen?.(artifact.id)} type="button">{labels.open}</button>
          </li>
        ))}</ul>
      )}
    </section>
  );
}

export interface AgentMemorySettingsProps {
  className?: string;
  labels?: Partial<{ title: string }>;
  onToggle?: ((id: string, enabled: boolean) => void) | undefined;
  settings: readonly AgentMemorySetting[];
}

export function AgentMemorySettings(props: AgentMemorySettingsProps) {
  const labels = { title: "Memory", ...props.labels };
  return (
    <section className={`zebra-agent-resources zebra-agent-memory-settings ${props.className ?? ""}`.trim()}>
      <h3>{labels.title}</h3>
      <ul>{props.settings.map((setting) => (
        <li key={setting.id}>
          <span className="zebra-agent-resources__main"><strong>{setting.label}</strong><small>{setting.description}</small></span>
          <label className="zebra-agent-memory-settings__toggle">
            <input aria-label={setting.label} checked={setting.enabled} disabled={setting.disabled || !props.onToggle} onChange={(event) => props.onToggle?.(setting.id, event.target.checked)} type="checkbox" />
            <span aria-hidden="true" />
          </label>
        </li>
      ))}</ul>
    </section>
  );
}
