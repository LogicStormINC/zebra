"use client";

import React, { useId, useRef, type CSSProperties, type KeyboardEvent } from "react";
import type {
  AgentComposerAttachment,
  AgentComposerMetrics,
  AgentComposerOption,
} from "@zebra-agent/ui-contracts";
import { createAgentThemeStyle, type AgentThemeTokens } from "../theme.ts";

export interface AgentComposerSuggestion {
  label: string;
  value: string;
}

export interface AgentComposerLabels {
  addAttachment: string;
  cacheHitRate: string;
  capability: string;
  contextCapacity: string;
  contextComposition: string;
  contextCompositionUnavailable?: string;
  contextBreakdownBasis?: string;
  contextEstimateMethod?: string;
  contextUnavailable: string;
  continue: string;
  model: string;
  pause: string;
  pausing: string;
  queued: (count: number) => string;
  reasoning: string;
  removeAttachment: (name: string) => string;
  send: string;
}

type ResolvedAgentComposerLabels = AgentComposerLabels & Required<Pick<
  AgentComposerLabels,
  "contextCompositionUnavailable" | "contextBreakdownBasis" | "contextEstimateMethod"
>>;

export interface AgentComposerProps {
  acceptedFileTypes?: string;
  attachments: readonly AgentComposerAttachment[];
  busy: boolean;
  capabilityOptions: readonly AgentComposerOption[];
  capabilityValue: string;
  canContinue: boolean;
  className?: string;
  disabled: boolean;
  labels?: Partial<AgentComposerLabels>;
  maxAttachments?: number;
  metrics: AgentComposerMetrics;
  modelOptions: readonly AgentComposerOption[];
  modelValue: string;
  onCapabilityChange: (value: string) => void;
  onContinue: () => void;
  onFilesSelected: (files: FileList | null) => void;
  onModelChange: (value: string) => void;
  onPause: () => void;
  onReasoningChange: (value: string) => void;
  onRemoveAttachment: (id: string) => void;
  onSubmit: () => void;
  onSuggestionPick: (value: string) => void;
  onValueChange: (value: string) => void;
  pausing: boolean;
  placeholder?: string;
  queueCount: number;
  reasoningOptions: readonly AgentComposerOption[];
  reasoningValue: string;
  suggestions: readonly AgentComposerSuggestion[];
  theme?: "dark" | "light";
  themeTokens?: Partial<AgentThemeTokens>;
  value: string;
}

const DEFAULT_LABELS: ResolvedAgentComposerLabels = {
  addAttachment: "Add attachment",
  cacheHitRate: "Average cache hit rate",
  capability: "Capability",
  contextCapacity: "Context capacity",
  contextComposition: "Estimated composition",
  contextCompositionUnavailable: "Composition was not recorded for this call",
  contextBreakdownBasis: "Accounting basis",
  contextEstimateMethod: "Estimate method",
  contextUnavailable: "No model usage yet",
  continue: "Continue",
  model: "Model",
  pause: "Pause",
  pausing: "Pausing",
  queued: (count) => `${count} queued`,
  reasoning: "Reasoning",
  removeAttachment: (name) => `Remove ${name}`,
  send: "Send",
};

export function AgentComposer(props: AgentComposerProps) {
  const fileInput = useRef<HTMLInputElement>(null);
  const labels: ResolvedAgentComposerLabels = {
    ...DEFAULT_LABELS,
    ...props.labels,
    contextCompositionUnavailable: props.labels?.contextCompositionUnavailable ?? DEFAULT_LABELS.contextCompositionUnavailable,
    contextBreakdownBasis: props.labels?.contextBreakdownBasis ?? DEFAULT_LABELS.contextBreakdownBasis,
    contextEstimateMethod: props.labels?.contextEstimateMethod ?? DEFAULT_LABELS.contextEstimateMethod,
  };
  const maxAttachments = props.maxAttachments ?? 4;
  const submitDisabled = props.disabled || props.pausing ||
    (!props.busy && !props.canContinue && !props.value.trim());

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    const composing = event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229;
    if (event.key !== "Enter" || event.shiftKey || event.ctrlKey || event.altKey ||
      event.metaKey || composing) return;
    event.preventDefault();
    if (!submitDisabled && !props.busy && !props.canContinue) props.onSubmit();
  }

  const action = props.busy
    ? { label: props.pausing ? labels.pausing : labels.pause, onClick: props.onPause, symbol: "■" }
    : props.canContinue
      ? { label: labels.continue, onClick: props.onContinue, symbol: "▶" }
      : { label: labels.send, onClick: props.onSubmit, symbol: "↑" };

  return (
    <section className={`zebra-agent-composer ${props.className ?? ""}`.trim()} data-theme={props.theme} style={createAgentThemeStyle(props.themeTokens)}>
      <textarea
        aria-label={props.placeholder || labels.send}
        className="zebra-agent-composer__input"
        disabled={props.disabled}
        onChange={(event) => props.onValueChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={props.placeholder}
        rows={2}
        value={props.value}
      />

      {props.attachments.length > 0 ? (
        <div aria-label="Attachments" className="zebra-agent-composer__attachments">
          {props.attachments.map((item) => (
            <span className="zebra-agent-composer__attachment" key={item.id}>
              <span aria-hidden="true" className="zebra-agent-composer__file-kind">
                {item.isImage ? "IMG" : "DOC"}
              </span>
              <span className="zebra-agent-composer__file-name">{item.name}</span>
              <button
                aria-label={labels.removeAttachment(item.name)}
                className="zebra-agent-composer__remove"
                disabled={props.disabled}
                onClick={() => props.onRemoveAttachment(item.id)}
                type="button"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      ) : null}

      {!props.busy && props.suggestions.length > 0 ? (
        <div aria-label="Suggestions" className="zebra-agent-composer__suggestions">
          {props.suggestions.map((item) => (
            <button
              className="zebra-agent-composer__suggestion"
              disabled={props.disabled}
              key={item.value}
              onClick={() => props.onSuggestionPick(item.value)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : null}

      <footer className="zebra-agent-composer__footer">
        <div className="zebra-agent-composer__leading">
          <input
            accept={props.acceptedFileTypes}
            aria-hidden="true"
            className="zebra-agent-composer__file-input"
            disabled={props.disabled || props.attachments.length >= maxAttachments}
            multiple
            onChange={(event) => {
              props.onFilesSelected(event.currentTarget.files);
              event.currentTarget.value = "";
            }}
            ref={fileInput}
            tabIndex={-1}
            type="file"
          />
          <button
            aria-label={labels.addAttachment}
            className="zebra-agent-composer__icon-button"
            disabled={props.disabled || props.attachments.length >= maxAttachments}
            onClick={() => fileInput.current?.click()}
            type="button"
          >
            <span aria-hidden="true">＋</span>
          </button>
          {props.queueCount > 0 ? (
            <span className="zebra-agent-composer__queue">{labels.queued(props.queueCount)}</span>
          ) : null}
        </div>

        <div className="zebra-agent-composer__controls">
          <ContextUsage labels={labels} metrics={props.metrics} />
          <SelectionControl
            ariaLabel={labels.capability}
            onChange={props.onCapabilityChange}
            options={props.capabilityOptions}
            value={props.capabilityValue}
          />
          <SelectionControl
            ariaLabel={labels.model}
            onChange={props.onModelChange}
            options={props.modelOptions}
            value={props.modelValue}
          />
          <SelectionControl
            ariaLabel={labels.reasoning}
            onChange={props.onReasoningChange}
            options={props.reasoningOptions}
            value={props.reasoningValue}
          />
          <button
            aria-label={action.label}
            className="zebra-agent-composer__action"
            disabled={submitDisabled}
            onClick={action.onClick}
            title={action.label}
            type="button"
          >
            <span aria-hidden="true">{action.symbol}</span>
          </button>
        </div>
      </footer>
    </section>
  );
}

function SelectionControl({
  ariaLabel,
  onChange,
  options,
  value,
}: {
  ariaLabel: string;
  onChange: (value: string) => void;
  options: readonly AgentComposerOption[];
  value: string;
}) {
  if (!options.length) return null;
  return (
    <label className="zebra-agent-composer__select-wrap">
      <span className="zebra-agent-composer__sr-only">{ariaLabel}</span>
      <select
        aria-label={ariaLabel}
        className="zebra-agent-composer__select"
        onChange={(event) => onChange(event.target.value)}
        value={value}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
      <span aria-hidden="true" className="zebra-agent-composer__chevron">⌄</span>
    </label>
  );
}

function ContextUsage({ labels, metrics }: {
  labels: ResolvedAgentComposerLabels;
  metrics: AgentComposerMetrics;
}) {
  const panelId = useId();
  const contextRatio = Number.isFinite(metrics.contextPercent) ? metrics.contextPercent ?? 0 : 0;
  const percent = Math.max(0, Math.min(100, Math.round(contextRatio * 100)));
  const hasUsage = metrics.contextPercent !== null;
  const cache = metrics.cacheHitRate === null || !Number.isFinite(metrics.cacheHitRate)
    ? "—"
    : `${(metrics.cacheHitRate * 100).toFixed(1)}%`;
  const parts = (metrics.contextBreakdown ?? []).filter((item) => Number.isFinite(item.tokens) && item.tokens >= 0);
  const partTotal = parts.reduce((total, item) => total + item.tokens, 0);
  const basis = metrics.contextBreakdownBasis?.trim();
  const estimateMethod = metrics.contextEstimateMethod?.trim();
  return (
    <div className="zebra-agent-composer__usage">
      <button
        aria-describedby={panelId}
        aria-label={hasUsage ? `${labels.contextCapacity} ${percent}%` : labels.contextUnavailable}
        className="zebra-agent-composer__usage-ring"
        style={{ "--zebra-agent-context-percent": `${percent}%` } as React.CSSProperties}
        type="button"
      >
        <span />
      </button>
      <div className="zebra-agent-composer__usage-panel" id={panelId} role="tooltip">
        <div className="zebra-agent-composer__usage-line">
          <strong>{labels.contextCapacity}</strong>
          <code>{hasUsage ? `${formatTokenCount(metrics.contextTokens)} / ${formatTokenCount(metrics.contextLimit)} · ${percent}%` : labels.contextUnavailable}</code>
        </div>
        <span className="zebra-agent-composer__meter"><span style={{ width: `${percent}%` }} /></span>
        {hasUsage ? (
          <>
            <span className="zebra-agent-composer__usage-section-label">{labels.contextComposition}</span>
            {parts.length && partTotal > 0 ? (
              <div className="zebra-agent-composer__usage-breakdown" aria-label={labels.contextComposition} role="list">
                {parts.map((item, index) => {
                  const partPercent = item.tokens / partTotal * 100;
                  const markerStyle = item.color
                    ? { "--zebra-agent-context-category-color": item.color } as CSSProperties
                    : { opacity: Math.max(0.4, 1 - index * 0.12) };
                  return (
                    <div className="zebra-agent-composer__usage-part" key={item.id} role="listitem">
                      <span className="zebra-agent-composer__usage-part-label">
                        <i aria-hidden="true" style={markerStyle} />
                        {item.label}
                      </span>
                      <code>{formatTokenCount(item.tokens)} · {partPercent < 0.05 ? "<0.1" : partPercent.toFixed(1)}%</code>
                    </div>
                  );
                })}
              </div>
            ) : <span className="zebra-agent-composer__usage-empty">{labels.contextCompositionUnavailable}</span>}
            {basis ? (
              <div className="zebra-agent-composer__usage-line zebra-agent-composer__usage-meta">
                <span>{labels.contextBreakdownBasis}</span><code>{basis}</code>
              </div>
            ) : null}
            {estimateMethod ? (
              <div className="zebra-agent-composer__usage-line zebra-agent-composer__usage-meta">
                <span>{labels.contextEstimateMethod}</span><code>{estimateMethod}</code>
              </div>
            ) : null}
          </>
        ) : null}
        <div className="zebra-agent-composer__usage-line zebra-agent-composer__usage-cache">
          <span>{labels.cacheHitRate}</span><strong>{cache}</strong>
        </div>
      </div>
    </div>
  );
}

function formatTokenCount(value: number | null): string {
  if (value === null) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}m`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(value);
}
