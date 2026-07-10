import { CheckCircleOutlined, CodeOutlined, FileOutlined } from "@ant-design/icons";
import { createStyles } from "antd-style";
import { extractAssistantInsights } from "../lib/message-insights";
import locale from "../_utils/local";

const useStyle = createStyles(({ css }) => {
  return {
    grid: css`
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(var(--zebra-grid-min), 1fr));
      gap: var(--zebra-space-sm);
    `,
    card: css`
      min-width: 0;
      border-radius: var(--zebra-radius-card);
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.07);
      padding: var(--zebra-space-sm) var(--zebra-space-md);
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-xs);
    `,
    title: css`
      display: flex;
      align-items: center;
      gap: var(--zebra-space-xs);
      color: rgba(255, 255, 255, 0.92);
      font-size: var(--zebra-font-size-sm);
      font-weight: var(--zebra-font-weight-semibold);
    `,
    icon: css`
      color: rgba(255, 255, 255, 0.6);
    `,
    list: css`
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-2xs);
      color: rgba(255, 255, 255, 0.72);
      font-size: var(--zebra-font-size-xs);
    `,
    row: css`
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      padding: var(--zebra-space-xs);
      border-radius: var(--zebra-radius-soft);
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.04);
    `,
  };
});

export function AssistantInsightCards({ content }: { content: string }) {
  const { commands, files, statuses } = extractAssistantInsights(content);
  const { styles } = useStyle();

  if (commands.length === 0 && files.length === 0 && statuses.length === 0) {
    return null;
  }

  return (
    <div className={styles.grid}>
      {files.length > 0 ? (
        <div className={styles.card}>
          <div className={styles.title}>
            <FileOutlined className={styles.icon} />
            <span>{locale.filesTouched}</span>
          </div>
          <div className={styles.list}>
            {files.map((item) => (
              <div className={styles.row} key={item}>
                {item}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {commands.length > 0 ? (
        <div className={styles.card}>
          <div className={styles.title}>
            <CodeOutlined className={styles.icon} />
            <span>{locale.commandsRun}</span>
          </div>
          <div className={styles.list}>
            {commands.map((item) => (
              <div className={styles.row} key={item}>
                {item}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {statuses.length > 0 ? (
        <div className={styles.card}>
          <div className={styles.title}>
            <CheckCircleOutlined className={styles.icon} />
            <span>{locale.validationNotes}</span>
          </div>
          <div className={styles.list}>
            {statuses.map((item) => (
              <div className={styles.row} key={item}>
                {item}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
