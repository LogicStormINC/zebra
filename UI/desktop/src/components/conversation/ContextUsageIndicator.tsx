import { BulbOutlined, CaretDownOutlined, RobotOutlined } from "@ant-design/icons";
import { Popover, Progress } from "antd";
import type { SessionEvent } from "../../types";
import { formatTokenCount, projectContextUsage } from "../../lib/context-usage";
import { useConversationPaneStyle } from "../CodexConversationPane.styles";

interface ContextUsageIndicatorProps {
  events: SessionEvent[];
}

export function ContextUsageIndicator({ events }: ContextUsageIndicatorProps) {
  const { styles } = useConversationPaneStyle();
  const usage = projectContextUsage(events);
  const percent = usage.utilization === null ? null : Math.round(usage.utilization * 1000) / 10;
  const cachePercent = usage.cacheHitRate === null ? null : Math.round(usage.cacheHitRate * 1000) / 10;
  const ringPercent = percent ?? 0;
  const pressureClass = usage.pressure === "critical"
    ? styles.contextRingCritical
    : usage.pressure === "warning"
      ? styles.contextRingWarning
      : usage.pressure === "normal" ? styles.contextRingNormal : styles.contextRingEmpty;
  const popover = (
    <div className={styles.contextPopover}>
      <div className={styles.contextPopoverHeader}>
        <strong>上下文容量</strong>
        <span>{formatTokenCount(usage.usedTokens)}/{formatTokenCount(usage.limitTokens)}{percent === null ? "" : ` (${percent}%)`}</span>
      </div>
      <Progress percent={ringPercent} showInfo={false} size="small" status={usage.pressure === "critical" ? "exception" : "normal"} />
      <div className={styles.contextPopoverMetric}>
        <span>平均缓存命中率</span>
        <strong>{cachePercent === null ? "暂无数据" : `${cachePercent}%`}</strong>
      </div>
      <small>基于当前会话的真实模型调用统计</small>
    </div>
  );

  return (
    <div className={styles.runtimeControls}>
      <Popover content={popover} placement="top" trigger={["hover", "focus", "click"]}>
        <button
          aria-label={percent === null ? "上下文容量暂无数据" : `上下文容量已使用 ${percent}%`}
          className={`${styles.contextRingButton} ${pressureClass}`}
          type="button"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24">
            <circle className="track" cx="12" cy="12" r="8" />
            <circle className="value" cx="12" cy="12" pathLength="100" r="8" strokeDasharray={`${ringPercent} 100`} />
          </svg>
        </button>
      </Popover>
      <Popover content="当前会话实际使用的模型由服务端运行时配置。" placement="top" trigger={["hover", "focus", "click"]}>
        <button className={styles.runtimeBadge} type="button">
          <RobotOutlined /><span>{usage.modelLabel}</span><CaretDownOutlined />
        </button>
      </Popover>
      <Popover content="推理强度来自最近一次模型调用；在运行时配置中修改。" placement="top" trigger={["hover", "focus", "click"]}>
        <button className={styles.runtimeBadge} type="button">
          <BulbOutlined /><span>{usage.reasoningLabel}</span><CaretDownOutlined />
        </button>
      </Popover>
    </div>
  );
}
