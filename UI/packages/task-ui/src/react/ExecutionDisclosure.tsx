import { ToolOutlined } from "@ant-design/icons";
import { createStyles } from "antd-style";
import type { TimelineToolItem } from "../core/timeline-projector.ts";

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
    min-width: 0;
    min-height: 44px;
    padding: 7px 8px;
    display: grid;
    grid-template-columns: 16px minmax(0, 1fr) auto auto;
    align-items: center;
    gap: 8px;
    color: var(--task-ui-text-muted, rgba(255, 255, 255, 0.68));
    font-size: 12px;
    line-height: 18px;
  `,
  icon: css`
    color: var(--task-ui-text-muted, rgba(255, 255, 255, 0.34));
  `,
  name: css`
    min-width: 0;
    overflow: hidden;
    color: var(--task-ui-text, rgba(255, 255, 255, 0.78));
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    text-overflow: ellipsis;
    white-space: nowrap;
  `,
  result: css`
    min-width: 0;
    overflow: hidden;
    color: var(--task-ui-text-muted, rgba(255, 255, 255, 0.55));
    text-overflow: ellipsis;
    white-space: nowrap;
  `,
  attempt: css`
    color: var(--task-ui-text-muted, rgba(255, 255, 255, 0.48));
    white-space: nowrap;
  `,
  status: css`
    padding: 1px 7px;
    border: 1px solid var(--task-ui-border, rgba(255, 255, 255, 0.09));
    border-radius: 999px;
    color: var(--task-ui-text-muted, rgba(255, 255, 255, 0.62));
    font-size: 11px;
    line-height: 16px;
    white-space: nowrap;
    [data-status="running"] &, [data-status="awaiting_approval"] & { color: var(--task-ui-accent, #f2a65a); }
    [data-status="failed"] &, [data-status="denied"] & { color: var(--task-ui-danger, #f28b82); }
    [data-status="completed"] & { color: var(--task-ui-success, #8fbc8f); }
  `,
}));

/**
 * Public-safe tool execution disclosure: identity and status only. Raw
 * arguments, full output, and policy reasons are never rendered here.
 */
export function ExecutionDisclosure({ tool }: { tool: TimelineToolItem }) {
  const { styles } = useStyle();
  return (
    <div className={styles.row} data-status={tool.status}>
      <ToolOutlined className={styles.icon} />
      <span className={styles.name}>{tool.toolName}</span>
      {tool.resultStatus ? <span className={styles.result}>{tool.resultStatus}</span> : null}
      <span className={styles.attempt}>attempt {tool.attemptNumber}</span>
      <span className={styles.status}>{STATUS_LABELS[tool.status]}</span>
    </div>
  );
}
