import { FileSearchOutlined } from "@ant-design/icons";
import { ThoughtChain } from "@ant-design/x";
import { Button, Tooltip } from "antd";
import { createStyles } from "antd-style";
import { useEffect, useState } from "react";
import { runtimeActivityTiming, type RuntimeActivityProjection } from "../core/runtime-activity.ts";

const useStyle = createStyles(({ css }) => ({
  row: css`
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    padding: 4px 2px;
    &:hover .zebra-runtime-action,
    &:focus-within .zebra-runtime-action { opacity: 1; }
  `,
  chain: css`
    flex: 1;
    min-width: 0;
  `,
  title: css`
    color: rgba(255, 255, 255, 0.82);
    font-size: 13px;
    font-weight: 500;
  `,
  detail: css`
    color: rgba(255, 255, 255, 0.42);
    font-size: 12px;
    line-height: 18px;
  `,
  action: css`
    flex: none;
    color: rgba(255, 255, 255, 0.42);
    opacity: 0;
    transition: opacity 160ms ease, color 160ms ease;
    @media (hover: none), (max-width: 640px), (prefers-reduced-motion: reduce) { opacity: 1; }
  `,
}));

interface RuntimeActivityCardProps {
  activity: RuntimeActivityProjection;
  onShowDetails: () => void;
  detailsLabel?: string;
  silentDetail?: string;
}

export function RuntimeActivityCard({
  activity,
  onShowDetails,
  detailsLabel = "查看运行日志",
  silentDetail = "仍在处理，暂时没有新的运行记录",
}: RuntimeActivityCardProps) {
  const { styles } = useStyle();
  const [mountedAt] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);
  const timing = runtimeActivityTiming(activity, now, mountedAt);
  const detail = timing.silent ? silentDetail : activity.detail;

  return (
    <section aria-live="polite" className={styles.row} role="status">
      <ThoughtChain.Item
        blink
        className={styles.chain}
        description={<span className={styles.detail}>{detail} · {timing.elapsedLabel}</span>}
        status="loading"
        title={<span className={styles.title}>{activity.title}</span>}
        variant="text"
      />
      <Tooltip title={detailsLabel}>
        <Button
          aria-label={detailsLabel}
          className={`${styles.action} zebra-runtime-action`}
          icon={<FileSearchOutlined />}
          onClick={onShowDetails}
          size="small"
          type="text"
        />
      </Tooltip>
    </section>
  );
}
