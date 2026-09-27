"use client";

import React, { useEffect, useRef, useState } from "react";
import type { AgentAppPart, AgentAppResource } from "@zebra-agent/ui-contracts";

export type AgentAppResourceResolver = (
  part: AgentAppPart,
) => AgentAppResource | Promise<AgentAppResource>;

export interface AgentAppMessage {
  id: string;
  method: string;
  params?: unknown;
  version: "2025-11-21";
}

export interface AgentAppBlockProps {
  allowedCapabilities?: readonly string[];
  labels: { failed: string; loading: string; unavailable: string };
  onMessage?: (message: AgentAppMessage, part: AgentAppPart) => void;
  part: AgentAppPart;
  resolveAppResource?: AgentAppResourceResolver;
}

export function AgentAppBlock(props: AgentAppBlockProps) {
  const [resource, setResource] = useState<AgentAppResource>();
  const [failed, setFailed] = useState(false);
  const frame = useRef<HTMLIFrameElement>(null);
  useEffect(() => {
    if (props.part.state !== "ready" || !props.resolveAppResource) return;
    let active = true;
    setFailed(false);
    void Promise.resolve(props.resolveAppResource(props.part)).then(
      (value) => {
        if (!active || !validResource(props.part, value, props.allowedCapabilities ?? [])) {
          if (active) setFailed(true);
          return;
        }
        setResource(value);
      },
      () => { if (active) setFailed(true); },
    );
    return () => { active = false; };
  }, [props.allowedCapabilities, props.part, props.resolveAppResource]);
  useEffect(() => {
    if (!resource || !props.onMessage) return;
    const receive = (event: MessageEvent) => {
      if (event.source !== frame.current?.contentWindow || event.origin !== resource.allowedOrigin) return;
      const message = parseMessage(event.data);
      if (message) props.onMessage?.(message, props.part);
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, [props.onMessage, props.part, resource]);
  if (props.part.state === "failed" || failed) {
    return <div className="zebra-agent-app-fallback" role="alert">{props.labels.failed}</div>;
  }
  if (!resource) {
    return <div className="zebra-agent-app-fallback" role="status">{props.resolveAppResource ? props.labels.loading : props.labels.unavailable}</div>;
  }
  return (
    <section className="zebra-agent-app">
      <header><strong>{props.part.title}</strong>{props.part.description ? <span>{props.part.description}</span> : null}</header>
      <iframe
        allow="clipboard-read 'none'; clipboard-write 'none'; geolocation 'none'; microphone 'none'; camera 'none'"
        ref={frame}
        sandbox="allow-forms allow-scripts"
        src={resource.url}
        title={props.part.title}
      />
    </section>
  );
}

function validResource(part: AgentAppPart, resource: AgentAppResource, allowed: readonly string[]) {
  if (resource.resourceUri !== part.resourceUri || resource.version !== "2025-11-21") return false;
  let origin: string;
  try { origin = new URL(resource.url).origin; } catch { return false; }
  if (origin !== resource.allowedOrigin || !origin.startsWith("https://")) return false;
  const granted = new Set(resource.capabilities);
  const hostAllowed = new Set(allowed);
  return (part.requestedCapabilities ?? []).every((capability) => granted.has(capability) && hostAllowed.has(capability));
}

function parseMessage(value: unknown): AgentAppMessage | undefined {
  if (!value || typeof value !== "object") return undefined;
  const candidate = value as Record<string, unknown>;
  if (
    candidate.version !== "2025-11-21" ||
    typeof candidate.id !== "string" || !candidate.id || candidate.id.length > 128 ||
    typeof candidate.method !== "string" || !candidate.method || candidate.method.length > 128
  ) return undefined;
  return { id: candidate.id, method: candidate.method, params: candidate.params, version: candidate.version };
}
