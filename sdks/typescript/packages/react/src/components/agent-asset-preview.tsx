"use client";

import React, { useEffect, useMemo, useState, type ReactNode } from "react";
import { AgentImageBlock, AgentVideoBlock, useArtifactAccess, type AgentArtifactResolver } from "./agent-media.tsx";

export interface AgentPreviewAsset {
  artifactId: string;
  fileName: string;
  mimeType: string;
  sizeBytes?: number;
  state?: "processing" | "ready" | "failed";
}

export interface AgentAssetPreviewProps {
  allowSandboxedHtml?: boolean;
  asset: AgentPreviewAsset;
  className?: string;
  loadText?: (url: string, maxBytes: number) => Promise<string>;
  maxTextBytes?: number;
  renderChart?: (spec: unknown) => ReactNode;
  renderMarkdown?: (content: string) => ReactNode;
  resolveArtifact: AgentArtifactResolver;
}

type PreviewKind = "audio" | "csv" | "html" | "image" | "json" | "markdown" | "pdf" | "text" | "vega" | "video" | "unsupported";

export function AgentAssetPreview({
  allowSandboxedHtml = false,
  asset,
  className,
  loadText = loadPreviewText,
  maxTextBytes = 1_000_000,
  renderChart,
  renderMarkdown,
  resolveArtifact,
}: AgentAssetPreviewProps) {
  const state = asset.state ?? "ready";
  const access = useArtifactAccess(resolveArtifact, asset.artifactId, "preview", state);
  const kind = previewKind(asset.mimeType, asset.fileName);
  const textual = ["csv", "json", "markdown", "text", "vega"].includes(kind);
  const text = usePreviewText(textual ? access.access?.url : undefined, maxTextBytes, loadText);
  const body = renderPreview({
    accessUrl: access.access?.url,
    allowSandboxedHtml,
    asset,
    kind,
    renderChart,
    renderMarkdown,
    resolveArtifact,
    state,
    text,
  });
  return <section className={`zebra-agent-asset-preview ${className ?? ""}`.trim()}>{body}</section>;
}

function renderPreview(input: {
  accessUrl: string | undefined;
  allowSandboxedHtml: boolean;
  asset: AgentPreviewAsset;
  kind: PreviewKind;
  renderChart: ((spec: unknown) => ReactNode) | undefined;
  renderMarkdown: ((content: string) => ReactNode) | undefined;
  resolveArtifact: AgentArtifactResolver;
  state: "processing" | "ready" | "failed";
  text: PreviewTextState;
}) {
  const {
    accessUrl,
    allowSandboxedHtml,
    asset,
    kind,
    renderChart,
    renderMarkdown,
    resolveArtifact,
    state,
    text,
  } = input;
  if (state === "failed") return <PreviewNotice label="Preview failed" role="alert" />;
  if (!accessUrl) return <PreviewNotice label="Loading preview" role="status" />;
  if (kind === "image") {
    return <AgentImageBlock labels={mediaLabels} part={{ alt: asset.fileName, artifactId: asset.artifactId, fileName: asset.fileName, id: `${asset.artifactId}:image`, mimeType: asset.mimeType, state, type: "image" }} resolveArtifact={resolveArtifact} />;
  }
  if (kind === "video") {
    return <AgentVideoBlock labels={mediaLabels} part={{ artifactId: asset.artifactId, fileName: asset.fileName, id: `${asset.artifactId}:video`, mimeType: asset.mimeType, state, title: asset.fileName, type: "video" }} resolveArtifact={resolveArtifact} />;
  }
  if (kind === "audio") return <audio className="zebra-agent-asset-preview__audio" controls preload="metadata" src={accessUrl} />;
  if (kind === "pdf") return <iframe className="zebra-agent-asset-preview__frame" src={accessUrl} title={asset.fileName} />;
  if (kind === "html") {
    return allowSandboxedHtml
      ? <iframe className="zebra-agent-asset-preview__frame" sandbox="" src={accessUrl} title={asset.fileName} />
      : <PreviewNotice label="HTML preview is disabled by the host" role="note" />;
  }
  if (!text.value) return <PreviewNotice label={text.error ?? "Loading preview"} role={text.error ? "alert" : "status"} />;
  if (kind === "markdown") return renderMarkdown ? renderMarkdown(text.value) : <pre className="zebra-agent-asset-preview__code">{text.value}</pre>;
  if (kind === "json") return <pre className="zebra-agent-asset-preview__code">{prettyJson(text.value)}</pre>;
  if (kind === "csv") return <CsvPreview text={text.value} />;
  if (kind === "vega") {
    const spec = parseJson(text.value);
    return spec && renderChart ? renderChart(spec) : <pre className="zebra-agent-asset-preview__code">{prettyJson(text.value)}</pre>;
  }
  if (kind === "text") return <pre className="zebra-agent-asset-preview__code">{text.value}</pre>;
  return <PreviewNotice label="Preview is not available for this file type" role="note" />;
}

type PreviewTextState = { error?: string; value?: string };

function usePreviewText(
  url: string | undefined,
  limit: number,
  loader: (url: string, maxBytes: number) => Promise<string>,
) {
  const [state, setState] = useState<PreviewTextState>({});
  useEffect(() => {
    if (!url) { setState({}); return; }
    let active = true;
    void loader(url, limit).then((value) => {
      if (active) setState({ value });
    }).catch((error: unknown) => { if (active) setState({ error: error instanceof Error ? error.message : "Preview failed" }); });
    return () => { active = false; };
  }, [limit, loader, url]);
  return state;
}

async function loadPreviewText(url: string, limit: number) {
  const response = await fetch(url, { credentials: "include" });
  if (!response.ok) throw new Error(`Preview request failed (${response.status})`);
  const declared = Number(response.headers.get("content-length") || 0);
  if (declared > limit) throw new Error("Preview is too large; download the file to view it");
  const value = await response.text();
  if (new TextEncoder().encode(value).byteLength > limit) {
    throw new Error("Preview is too large; download the file to view it");
  }
  return value;
}

function CsvPreview({ text }: { text: string }) {
  const rows = useMemo(() => parseDelimited(text).slice(0, 201), [text]);
  if (!rows.length) return <PreviewNotice label="This table is empty" role="note" />;
  const [head, ...body] = rows;
  if (!head) return <PreviewNotice label="This table is empty" role="note" />;
  return <div className="zebra-agent-asset-preview__table-wrap"><table><thead><tr>{head.map((cell, index) => <th key={`${cell}:${index}`}>{cell}</th>)}</tr></thead><tbody>{body.map((row, rowIndex) => <tr key={rowIndex}>{head.map((_, index) => <td key={index}>{row[index] ?? ""}</td>)}</tr>)}</tbody></table>{rows.length === 201 ? <p>Showing the first 200 rows</p> : null}</div>;
}

function parseDelimited(text: string) {
  const delimiter = text.includes("\t") && !text.includes(",") ? "\t" : ",";
  const rows: string[][] = [];
  let cell = "", row: string[] = [], quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === '"' && quoted && text[index + 1] === '"') { cell += '"'; index += 1; }
    else if (char === '"') quoted = !quoted;
    else if (char === delimiter && !quoted) { row.push(cell); cell = ""; }
    else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && text[index + 1] === "\n") index += 1;
      row.push(cell); rows.push(row); row = []; cell = "";
    } else cell += char;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

function previewKind(mime: string, name: string): PreviewKind {
  const normalized = mime.toLowerCase();
  const lowerName = name.toLowerCase();
  const extension = lowerName.split(".").pop();
  if (normalized.startsWith("image/")) return "image";
  if (normalized.startsWith("video/")) return "video";
  if (normalized.startsWith("audio/")) return "audio";
  if (normalized === "application/pdf" || extension === "pdf") return "pdf";
  if (normalized.includes("markdown") || ["md", "mdx"].includes(extension ?? "")) return "markdown";
  if (normalized.includes("vega") || lowerName.endsWith(".vl.json")) return "vega";
  if (normalized.includes("json") || extension === "json") return "json";
  if (normalized.includes("csv") || normalized.includes("tab-separated") || ["csv", "tsv"].includes(extension ?? "")) return "csv";
  if (normalized === "text/html" || extension === "html") return "html";
  if (normalized.startsWith("text/") || ["log", "txt", "yaml", "yml"].includes(extension ?? "")) return "text";
  return "unsupported";
}

function parseJson(value: string) { try { return JSON.parse(value) as unknown; } catch { return null; } }
function prettyJson(value: string) { const parsed = parseJson(value); return parsed === null ? value : JSON.stringify(parsed, null, 2); }
function PreviewNotice({ label, role }: { label: string; role: "alert" | "note" | "status" }) { return <div className="zebra-agent-asset-preview__notice" role={role}>{label}</div>; }

const mediaLabels = { close: "Close preview", failed: "Preview failed", loading: "Loading preview", openImage: "Open image preview", unavailable: "Media unavailable" };
