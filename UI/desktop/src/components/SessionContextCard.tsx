import { BranchesOutlined, FolderOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import { Tag } from "antd";
import { createStyles } from "antd-style";
import type { SessionSummary } from "../types";

const useStyle = createStyles(({ css }) => {
  return {
    card: css`
      margin: 0 0 var(--zebra-space-xl);
      padding: var(--zebra-space-md) var(--zebra-space-lg);
      border-radius: var(--zebra-radius-large);
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.045), rgba(255, 255, 255, 0.025));
      border: 1px solid rgba(255, 255, 255, 0.08);
      box-shadow: var(--zebra-shadow-md);
    `,
    header: css`
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--zebra-space-sm);
      margin-bottom: var(--zebra-space-md);
      flex-wrap: wrap;
    `,
    title: css`
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-2xs);
      strong {
        font-size: var(--zebra-font-size-md);
        font-weight: var(--zebra-font-weight-semibold);
        color: rgba(255, 255, 255, 0.94);
      }
      span {
        color: rgba(255, 255, 255, 0.5);
        font-size: var(--zebra-font-size-xs);
      }
    `,
    grid: css`
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(var(--zebra-grid-context), 1fr));
      gap: var(--zebra-space-xs);
    `,
    item: css`
      min-width: 0;
      padding: var(--zebra-space-sm) var(--zebra-space-md);
      border-radius: var(--zebra-radius-soft);
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.05);
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-xs);
      span:first-child {
        color: rgba(255, 255, 255, 0.46);
        font-size: var(--zebra-font-size-2xs);
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }
      span:last-child {
        color: rgba(255, 255, 255, 0.9);
        font-size: var(--zebra-font-size-sm);
        font-weight: var(--zebra-font-weight-medium);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
    `,
    icon: css`
      margin-right: var(--zebra-space-xs);
      color: rgba(255, 255, 255, 0.52);
    `,
  };
});

function shortWorkspace(path?: string) {
  if (!path) {
    return "未绑定";
  }
  const parts = path.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

interface SessionContextCardProps {
  apiBaseUrl: string;
  session: SessionSummary;
}

export function SessionContextCard({ apiBaseUrl, session }: SessionContextCardProps) {
  const { styles } = useStyle();

  return (
    <section className={styles.card}>
      <div className={styles.header}>
        <div className={styles.title}>
          <strong>{session.title}</strong>
          <span>{session.session_id}</span>
        </div>
        <Tag color="geekblue">{session.status}</Tag>
      </div>
      <div className={styles.grid}>
        <div className={styles.item}>
          <span>Workspace</span>
          <span>
            <FolderOutlined className={styles.icon} />
            {shortWorkspace(session.workspace?.workspace_root)}
          </span>
        </div>
        <div className={styles.item}>
          <span>Execution</span>
          <span>
            <BranchesOutlined className={styles.icon} />
            seq {session.current_sequence} / attempt {session.workspace?.last_attempt_number ?? 0}
          </span>
        </div>
        <div className={styles.item}>
          <span>Policy</span>
          <span>
            <SafetyCertificateOutlined className={styles.icon} />
            {session.workspace?.policy_profile ?? apiBaseUrl}
          </span>
        </div>
      </div>
    </section>
  );
}
