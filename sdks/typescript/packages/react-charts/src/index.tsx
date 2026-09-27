"use client";

import React, { useEffect, useRef, useState } from "react";
import type { Result as VegaEmbedResult } from "vega-embed";
import type { AgentChartPart, AgentChartTable, AgentJsonValue } from "@zebra-agent/ui-contracts";
import type { AgentPartRendererProps } from "@zebra-agent/react";

export interface AgentVegaLiteRendererOptions {
  maxInlineDataRows?: number;
  maxSpecBytes?: number;
}

export function createAgentVegaLiteRenderer(options: AgentVegaLiteRendererOptions = {}) {
  const maxInlineDataRows = options.maxInlineDataRows ?? 5_000;
  const maxSpecBytes = options.maxSpecBytes ?? 256_000;
  return function AgentVegaLiteRenderer(props: AgentPartRendererProps) {
    if (props.part.type !== "chart") return null;
    return <VegaLiteChart context={props.context} maxInlineDataRows={maxInlineDataRows} maxSpecBytes={maxSpecBytes} part={props.part} />;
  };
}

export const AgentVegaLiteRenderer = createAgentVegaLiteRenderer();

function VegaLiteChart({ context, maxInlineDataRows, maxSpecBytes, part }: {
  context: AgentPartRendererProps["context"];
  maxInlineDataRows: number;
  maxSpecBytes: number;
  part: AgentChartPart;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string>();
  useEffect(() => {
    if (part.state !== "ready" || !container.current) return;
    let active = true;
    let result: VegaEmbedResult | undefined;
    void loadSpec(part, context.resolveArtifact).then(async (spec) => {
      validateVegaLiteSpec(spec, { maxInlineDataRows, maxSpecBytes, specVersion: part.specVersion });
      const { default: embed } = await import("vega-embed");
      if (!active || !container.current) return;
      result = await embed(container.current, spec as never, {
        actions: { export: true, source: false, compiled: false, editor: false },
        mode: "vega-lite",
        renderer: "svg",
        tooltip: true,
      });
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "chart_render_failed");
    });
    return () => {
      active = false;
      result?.view.finalize();
    };
  }, [context.resolveArtifact, maxInlineDataRows, maxSpecBytes, part]);
  if (part.state === "processing") return <ChartFallback description={part.description} label={context.labels.loading} table={part.table} title={part.title} />;
  if (part.state === "failed" || error) return <ChartFallback description={part.description} label={context.labels.failed} table={part.table} title={part.title} />;
  return (
    <figure className="zebra-agent-chart">
      <figcaption><strong>{part.title}</strong><span>{part.description}</span></figcaption>
      <div aria-label={part.description} className="zebra-agent-chart__canvas" ref={container} role="img" />
      {part.table ? <details><summary>View chart data</summary><AgentChartDataTable table={part.table} /></details> : null}
    </figure>
  );
}

function ChartFallback({ description, label, table, title }: { description: string; label: string; table?: AgentChartTable; title: string }) {
  return <section className="zebra-agent-chart zebra-agent-chart--fallback" role="status"><strong>{title}</strong><span>{description}</span><small>{label}</small>{table ? <AgentChartDataTable table={table} /> : null}</section>;
}

export function AgentChartDataTable({ table }: { table: AgentChartTable }) {
  return (
    <div className="zebra-agent-chart__table-scroll">
      <table><thead><tr>{table.columns.map((column) => <th key={column} scope="col">{column}</th>)}</tr></thead><tbody>{table.rows.map((row, index) => <tr key={index}>{table.columns.map((_, column) => <td key={column}>{displayJson(row[column])}</td>)}</tr>)}</tbody></table>
    </div>
  );
}

async function loadSpec(part: AgentChartPart, resolver: AgentPartRendererProps["context"]["resolveArtifact"]): Promise<AgentJsonValue> {
  if (part.spec) return part.spec;
  if (!part.specArtifactId || !resolver) throw new Error("chart_spec_unavailable");
  const access = await resolver(part.specArtifactId, "data");
  const response = await fetch(access.url, { credentials: "same-origin" });
  if (!response.ok) throw new Error("chart_spec_unavailable");
  return await response.json() as AgentJsonValue;
}

export function validateVegaLiteSpec(spec: AgentJsonValue, options: { maxInlineDataRows: number; maxSpecBytes: number; specVersion: string }) {
  if (!spec || Array.isArray(spec) || typeof spec !== "object") throw new Error("chart_spec_must_be_object");
  if (!options.specVersion.startsWith("6")) throw new Error("chart_spec_version_unsupported");
  const encoded = JSON.stringify(spec);
  if (new TextEncoder().encode(encoded).byteLength > options.maxSpecBytes) throw new Error("chart_spec_too_large");
  inspectNode(spec, options.maxInlineDataRows);
}

function inspectNode(value: AgentJsonValue, maxRows: number, key = "") {
  if (Array.isArray(value)) {
    if (key === "values" && value.length > maxRows) throw new Error("chart_inline_data_too_large");
    value.forEach((item) => inspectNode(item, maxRows));
    return;
  }
  if (!value || typeof value !== "object") return;
  for (const [childKey, child] of Object.entries(value)) {
    if (
      ["__proto__", "calculate", "constructor", "expr", "href", "labelExpr", "prototype", "url"].includes(childKey)
      || (["filter", "signal", "test"].includes(childKey) && typeof child === "string")
    ) {
      throw new Error("chart_external_or_executable_content_forbidden");
    }
    inspectNode(child, maxRows, childKey);
  }
}

function displayJson(value: AgentJsonValue | undefined) {
  if (value === undefined || value === null) return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
