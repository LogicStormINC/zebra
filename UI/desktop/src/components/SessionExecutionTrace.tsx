import { ToolOutlined } from "@ant-design/icons";
import { Tag } from "antd";
import { createStyles } from "antd-style";
import { projectAttemptTrace } from "../lib/session-trace";
import type { SessionEvent } from "../types";

const useStyle = createStyles(({ css }) => {
  return {
    shell: css`
      margin: 0 0 var(--zebra-space-xl);
      border-radius: var(--zebra-radius-large);
      padding: var(--zebra-space-md) var(--zebra-space-lg);
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.045), rgba(255, 255, 255, 0.025));
      border: 1px solid rgba(255, 255, 255, 0.07);
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-md);
    `,
    header: css`
      display: flex;
      align-items: center;
      gap: var(--zebra-space-sm);
      color: rgba(255, 255, 255, 0.92);
      font-size: var(--zebra-font-size-xs);
      font-weight: var(--zebra-font-weight-semibold);
    `,
    icon: css`
      color: rgba(255, 255, 255, 0.6);
    `,
    attempt: css`
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-md);
      padding: var(--zebra-space-sm) 0 0;
      border-top: 1px solid rgba(255, 255, 255, 0.05);
    `,
    attemptTitle: css`
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--zebra-space-sm);
      color: rgba(255, 255, 255, 0.86);
      font-size: var(--zebra-font-size-2xs);
      font-weight: var(--zebra-font-weight-semibold);
    `,
    toolList: css`
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-sm);
    `,
    toolCard: css`
      border-radius: var(--zebra-radius-soft);
      padding: var(--zebra-space-sm) var(--zebra-space-md);
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.05);
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-xs);
    `,
    toolHead: css`
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--zebra-space-sm);
      color: rgba(255, 255, 255, 0.9);
      font-size: var(--zebra-font-size-sm);
      font-weight: var(--zebra-font-weight-medium);
    `,
    toolMeta: css`
      color: rgba(255, 255, 255, 0.52);
      font-size: var(--zebra-font-size-2xs);
      white-space: pre-wrap;
      word-break: break-word;
    `,
    empty: css`
      color: rgba(255, 255, 255, 0.5);
      font-size: var(--zebra-font-size-xs);
    `,
  };
});

export function SessionExecutionTrace({ events }: { events: SessionEvent[] }) {
  const { styles } = useStyle();
  const attempts = projectAttemptTrace(events);

  if (attempts.length === 0) {
    return null;
  }

  return (
    <section className={styles.shell}>
      <div className={styles.header}>
        <ToolOutlined className={styles.icon} />
        <span>Execution trace</span>
      </div>
      {attempts.map((attempt) => (
        <div className={styles.attempt} key={attempt.attemptNumber}>
          <div className={styles.attemptTitle}>
            <span>Attempt {attempt.attemptNumber}</span>
            <Tag color="blue">{attempt.tools.length} tools</Tag>
          </div>
          {attempt.tools.length === 0 ? (
            <div className={styles.empty}>No tool calls recorded for this attempt.</div>
          ) : (
            <div className={styles.toolList}>
              {attempt.tools.map((tool, index) => (
                <div className={styles.toolCard} key={`${attempt.attemptNumber}-${tool.toolName}-${index}`}>
                  <div className={styles.toolHead}>
                    <span>{tool.toolName}</span>
                    <Tag color={tool.status === "executed" ? "green" : "red"}>{tool.status}</Tag>
                  </div>
                  {Object.keys(tool.arguments).length > 0 ? (
                    <div className={styles.toolMeta}>args: {JSON.stringify(tool.arguments)}</div>
                  ) : null}
                  {tool.output ? <div className={styles.toolMeta}>output: {tool.output.slice(0, 240)}</div> : null}
                  {tool.policyDecision ? <div className={styles.toolMeta}>policy: {tool.policyDecision}</div> : null}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </section>
  );
}
