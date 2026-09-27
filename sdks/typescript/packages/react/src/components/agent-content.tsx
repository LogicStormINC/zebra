"use client";

import React, { type ComponentType, type ReactNode } from "react";
import type {
  AgentAppPart,
  AgentContentPart,
  AgentFilePart,
  AgentMessage,
  AgentTextPart,
} from "@zebra-agent/ui-contracts";
import { AgentAppBlock, type AgentAppMessage, type AgentAppResourceResolver } from "./agent-app.tsx";
import { AgentImageBlock, AgentVideoBlock, useArtifactAccess, type AgentArtifactResolver, type AgentMediaLabels } from "./agent-media.tsx";

export interface AgentContentLabels extends AgentMediaLabels {
  appFailed: string;
  appUnavailable: string;
  download: string;
  failed: string;
  loading: string;
  unsupported: string;
}

export interface AgentPartRendererProps {
  context: AgentContentRendererContext;
  message: AgentMessage;
  part: AgentContentPart;
}

export type AgentPartRenderer = ComponentType<AgentPartRendererProps>;
export type AgentRendererRegistry = Partial<Record<AgentContentPart["type"], AgentPartRenderer>>;

export interface AgentContentRendererContext {
  allowedAppCapabilities: readonly string[];
  labels: AgentContentLabels;
  onAppMessage?: ((message: AgentAppMessage, part: AgentAppPart) => void) | undefined;
  renderText?: ((part: AgentTextPart, message: AgentMessage) => ReactNode) | undefined;
  renderers?: AgentRendererRegistry | undefined;
  resolveAppResource?: AgentAppResourceResolver | undefined;
  resolveArtifact?: AgentArtifactResolver | undefined;
}

export interface AgentContentRendererProps extends Partial<AgentContentRendererContext> {
  message: AgentMessage;
}

const DEFAULT_LABELS: AgentContentLabels = {
  appFailed: "Interactive content failed to load",
  appUnavailable: "Interactive content is not available in this host",
  close: "Close preview",
  download: "Download",
  failed: "Content failed to load",
  loading: "Loading content",
  openImage: "Open image preview",
  unavailable: "This media cannot be played",
  unsupported: "Unsupported content",
};

export function AgentContentRenderer(props: AgentContentRendererProps) {
  const context: AgentContentRendererContext = {
    allowedAppCapabilities: props.allowedAppCapabilities ?? [],
    labels: { ...DEFAULT_LABELS, ...props.labels },
    onAppMessage: props.onAppMessage,
    renderText: props.renderText,
    renderers: props.renderers,
    resolveAppResource: props.resolveAppResource,
    resolveArtifact: props.resolveArtifact,
  };
  const parts = props.message.parts?.length
    ? props.message.parts
    : [{ id: `${props.message.id}:text`, state: props.message.status === "failed" ? "failed" as const : "ready" as const, type: "text" as const, format: "plain" as const, text: props.message.content }];
  return <div className="zebra-agent-content">{parts.map((part) => <AgentPart key={part.id} context={context} message={props.message} part={part} />)}</div>;
}

function AgentPart(props: AgentPartRendererProps) {
  const custom = props.context.renderers?.[props.part.type];
  if (custom) return React.createElement(custom, props);
  const { context, message, part } = props;
  if (part.type === "text") return <AgentTextBlock context={context} message={message} part={part} />;
  if (part.type === "image") return <AgentImageBlock labels={context.labels} part={part} {...(context.resolveArtifact ? { resolveArtifact: context.resolveArtifact } : {})} />;
  if (part.type === "video") return <AgentVideoBlock labels={context.labels} part={part} {...(context.resolveArtifact ? { resolveArtifact: context.resolveArtifact } : {})} />;
  if (part.type === "file") return <AgentFileBlock context={context} part={part} />;
  if (part.type === "app") return <AgentAppBlock allowedCapabilities={context.allowedAppCapabilities} labels={{ failed: context.labels.appFailed, loading: context.labels.loading, unavailable: context.labels.appUnavailable }} part={part} {...(context.onAppMessage ? { onMessage: context.onAppMessage } : {})} {...(context.resolveAppResource ? { resolveAppResource: context.resolveAppResource } : {})} />;
  return <AgentUnsupportedBlock label={context.labels.unsupported} />;
}

function AgentTextBlock({ context, message, part }: { context: AgentContentRendererContext; message: AgentMessage; part: AgentTextPart }) {
  if (part.state === "failed") return <div className="zebra-agent-content__error" role="alert">{context.labels.failed}</div>;
  return <div className={`zebra-agent-content__text zebra-agent-content__text--${part.format}`}>{context.renderText ? context.renderText(part, message) : part.text}</div>;
}

function AgentFileBlock({ context, part }: { context: AgentContentRendererContext; part: AgentFilePart }) {
  const download = useArtifactAccess(context.resolveArtifact, part.artifactId, "download", part.state);
  return (
    <section className="zebra-agent-file">
      <span aria-hidden="true" className="zebra-agent-file__icon">↧</span>
      <span className="zebra-agent-file__main"><strong>{part.name}</strong><small>{part.description ?? part.mimeType}</small></span>
      {download.access ? <a download={part.name} href={download.access.url}>{context.labels.download}</a> : <span>{part.state === "failed" || download.status === "failed" ? context.labels.failed : context.labels.loading}</span>}
    </section>
  );
}

function AgentUnsupportedBlock({ label }: { label: string }) {
  return <div className="zebra-agent-content__unsupported" role="note">{label}</div>;
}
