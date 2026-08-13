import { RightOutlined } from "@ant-design/icons";
import { createStyles, keyframes } from "antd-style";
import { Fragment, type ReactNode } from "react";
import { isActiveToolStatus, type TimelineToolItem } from "../core/timeline-projector.ts";
import { ExecutionDisclosure } from "./ExecutionDisclosure.tsx";

const shimmer = keyframes`
  0%, 100% { opacity: 1; }
  50% { opacity: 0.42; }
`;

const useStyle = createStyles(({ css }) => ({
  group: css`
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.015);
    overflow: hidden;
    &[open] {
      background: rgba(255, 255, 255, 0.022);
    }
  `,
  summary: css`
    min-height: 40px;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    cursor: pointer;
    color: rgba(255, 255, 255, 0.72);
    font-size: 13px;
    line-height: 20px;
    list-style: none;
    user-select: none;
    &::-webkit-details-marker {
      display: none;
    }
    &:hover {
      color: rgba(255, 255, 255, 0.9);
    }
    &:focus-visible {
      border-radius: 6px;
      outline: 2px solid rgba(245, 158, 11, 0.7);
      outline-offset: -2px;
    }
  `,
  chevron: css`
    flex: 0 0 auto;
    color: rgba(255, 255, 255, 0.4);
    font-size: 11px;
    transition: transform 160ms ease;
    details[open] & {
      transform: rotate(90deg);
    }
  `,
  label: css`
    font-weight: 500;
  `,
  labelActive: css`
    animation: ${shimmer} 1.5s ease-in-out infinite;
  `,
  count: css`
    color: rgba(255, 255, 255, 0.45);
    font-size: 12px;
  `,
  spacer: css`
    flex: 1;
  `,
  failed: css`
    color: #f28b82;
    font-size: 12px;
  `,
  body: css`
    display: grid;
  `,
}));

interface ToolCallGroupProps {
  tools: TimelineToolItem[];
  activeLabel?: string;
  label?: string;
  unitLabel?: string;
  failedLabel?: string;
  /** Consumer-provided detail renderer; defaults to the public-safe disclosure. */
  renderToolDetail?: (tool: TimelineToolItem) => ReactNode;
}

export function ToolCallGroup({
  tools,
  activeLabel = "正在调用工具…",
  label = "工具调用",
  unitLabel = "项",
  failedLabel = "failed",
  renderToolDetail = (tool) => <ExecutionDisclosure tool={tool} />,
}: ToolCallGroupProps) {
  const { styles, cx } = useStyle();
  const active = tools.some((tool) => isActiveToolStatus(tool.status));
  const failedCount = tools.filter((tool) => tool.status === "failed" || tool.status === "denied").length;

  return (
    <details className={styles.group}>
      <summary className={styles.summary}>
        <RightOutlined className={styles.chevron} />
        <span className={cx(styles.label, active && styles.labelActive)}>{active ? activeLabel : label}</span>
        <span className={styles.count}>· {tools.length} {unitLabel}</span>
        <span className={styles.spacer} />
        {failedCount ? <span className={styles.failed}>{failedCount} {failedLabel}</span> : null}
      </summary>
      <div className={styles.body}>
        {tools.map((tool) => (
          <Fragment key={tool.key}>{renderToolDetail(tool)}</Fragment>
        ))}
      </div>
    </details>
  );
}
