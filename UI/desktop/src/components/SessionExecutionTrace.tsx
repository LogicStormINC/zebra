import { ToolOutlined } from "@ant-design/icons";
import { createStyles } from "antd-style";
import type { TimelineToolItem } from "../lib/session-timeline";

const STATUS_LABELS: Record<TimelineToolItem["status"], string> = {
  proposed: "proposed",
  awaiting_approval: "awaiting approval",
  denied: "denied",
  running: "running",
  completed: "completed",
  failed: "failed",
};

const useStyle = createStyles(({ css }) => ({
  row: css`
    border-top: 1px solid rgba(255, 255, 255, 0.055);
    border-bottom: 1px solid rgba(255, 255, 255, 0.055);
    background: rgba(255, 255, 255, 0.012);
    &[open] { background: rgba(255, 255, 255, 0.025); }
  `,
  summary: css`
    min-width: 0;
    min-height: 44px;
    padding: 7px 8px;
    display: grid;
    grid-template-columns: 16px minmax(0, 1fr) auto auto;
    align-items: center;
    gap: 8px;
    color: rgba(255, 255, 255, 0.68);
    cursor: pointer;
    font-size: 12px;
    line-height: 18px;
    list-style-position: outside;
    &:focus-visible {
      border-radius: 6px;
      outline: 2px solid rgba(245, 158, 11, 0.7);
      outline-offset: 2px;
    }
    &::marker { color: rgba(255, 255, 255, 0.35); }
  `,
  icon: css`
    color: rgba(255, 255, 255, 0.34);
  `,
  name: css`
    min-width: 0;
    overflow: hidden;
    color: rgba(255, 255, 255, 0.78);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    text-overflow: ellipsis;
    white-space: nowrap;
  `,
  toolSummary: css`
    min-width: 0;
    display: flex;
    align-items: baseline;
    gap: 7px;
    overflow: hidden;
  `,
  outputPreview: css`
    min-width: 0;
    overflow: hidden;
    color: rgba(255, 255, 255, 0.55);
    font-family: inherit;
    text-overflow: ellipsis;
    white-space: nowrap;
  `,
  attempt: css`
    color: rgba(255, 255, 255, 0.48);
    white-space: nowrap;
  `,
  status: css`
    padding: 1px 7px;
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 999px;
    color: rgba(255, 255, 255, 0.62);
    font-size: 11px;
    line-height: 16px;
    white-space: nowrap;
    [data-status="running"] &, [data-status="awaiting_approval"] & { color: #f2a65a; }
    [data-status="failed"] &, [data-status="denied"] & { color: #f28b82; }
    [data-status="completed"] & { color: #8fbc8f; }
  `,
  body: css`
    display: grid;
    gap: 7px;
    padding: 2px 12px 12px 32px;
  `,
  detail: css`
    display: grid;
    grid-template-columns: 62px minmax(0, 1fr);
    gap: 10px;
    color: rgba(255, 255, 255, 0.66);
    font-size: 12px;
    line-height: 18px;
    dt { color: rgba(255, 255, 255, 0.5); }
    dd {
      min-width: 0;
      margin: 0;
      overflow-wrap: anywhere;
      white-space: pre-wrap;
    }
  `,
}));

function visibleText(value: unknown) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  if (!text) return "";
  return text.length > 900 ? `${text.slice(0, 900)}…` : text;
}

function outputPreview(value: string) {
  const text = value.replace(/\s+/gu, " ").trim();
  return text.length > 140 ? `${text.slice(0, 140)}…` : text;
}

export function SessionExecutionTrace({ tool }: { tool: TimelineToolItem }) {
  const { styles } = useStyle();
  const expanded = ["running", "failed", "denied", "awaiting_approval"].includes(tool.status);
  const preview = tool.status === "completed" ? outputPreview(tool.output) : "";
  const details = [
    Object.keys(tool.arguments).length ? ["Arguments", visibleText(tool.arguments)] : null,
    tool.output ? ["Output", visibleText(tool.output)] : null,
    tool.policyDecision ? ["Policy", visibleText([tool.policyDecision, tool.policyReason].filter(Boolean).join(" · "))] : null,
    tool.resultStatus ? ["Result", visibleText(tool.resultStatus)] : null,
  ].filter((detail): detail is string[] => Boolean(detail));

  return (
    <details className={styles.row} data-status={tool.status} open={expanded || undefined}>
      <summary className={styles.summary}>
        <ToolOutlined className={styles.icon} />
        <span className={styles.toolSummary}>
          <span className={styles.name}>{tool.toolName}</span>
          {preview ? <span className={styles.outputPreview}>— {preview}</span> : null}
        </span>
        <span className={styles.attempt}>attempt {tool.attemptNumber}</span>
        <span className={styles.status}>{STATUS_LABELS[tool.status]}</span>
      </summary>
      {details.length ? <dl className={styles.body}>{details.map(([label, value]) => (
        <div className={styles.detail} key={label}><dt>{label}</dt><dd>{value}</dd></div>
      ))}</dl> : null}
    </details>
  );
}
