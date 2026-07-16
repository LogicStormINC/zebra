import locale from "../../_utils/local";
import { sessionStatusLabel, sessionWorkspaceLabel } from "../../_utils/session-status";
import type { ConversationSeed } from "../../lib/chat-surface";
import type { SessionSummary } from "../../types";
import { useConversationPaneStyle } from "../CodexConversationPane.styles";

const suggestedActions = [
  { label: locale.hintDocs, prompt: "阅读当前工作空间中的资料，并总结关键结论。" },
  { label: locale.hintExplain, prompt: "解释当前任务上下文、约束和可用信息。" },
  { label: locale.hintDebug, prompt: "分析当前问题，给出有证据的原因和处理方案。" },
  { label: locale.hintImplement, prompt: "根据当前目标，使用可用工具完成下一步任务。" },
  { label: locale.hintShip, prompt: "验证当前结果，并列出验证证据和未解决风险。" },
];

interface WorkspaceIdleProps {
  composer: React.ReactNode;
  conversations: ConversationSeed[];
  currentConversation: string;
  launchError: string | null;
  onQuickAction: (prompt: string) => void;
  onSelectConversation: (key: string) => void;
  sessionSummaries: Record<string, SessionSummary | null>;
}

export function WorkspaceIdle({
  composer,
  conversations,
  currentConversation,
  launchError,
  onQuickAction,
  onSelectConversation,
  sessionSummaries,
}: WorkspaceIdleProps) {
  const { styles } = useConversationPaneStyle();
  const recentThreads = conversations.filter((item) => item.key !== currentConversation).slice(0, 5);
  const threadMeta = (item: ConversationSeed) => {
    const dayLabel = item.group === locale.pinned ? locale.todayGroup : item.group;
    const summary = sessionSummaries[item.key];
    return `${sessionStatusLabel(summary?.status)} · ${dayLabel} · ${sessionWorkspaceLabel(summary)}`;
  };

  return (
    <div className={styles.idleWorkspace}>
      <h2 className={styles.idleQuestion}>{locale.idlePromptTitle}</h2>
      <div className={styles.idleSubtitle}>{locale.idlePromptSubtitle}</div>
      {composer}
      <section className={styles.idleSection}>
        <div className={styles.idleSectionTitle}>{locale.suggestedActions}</div>
        <div className={styles.actionGrid}>
          {suggestedActions.map((action) => (
            <button
              className={styles.quickAction}
              disabled={Boolean(launchError)}
              key={action.label}
              onClick={() => onQuickAction(action.prompt)}
              type="button"
            >
              {action.label}
            </button>
          ))}
        </div>
      </section>
      <section className={styles.idleSection}>
        <div className={styles.idleSectionTitle}>{locale.continueTasks}</div>
        <div className={styles.recentGroup}>{locale.todayGroup}</div>
        <div className={styles.recentList}>
          {recentThreads.map((item) => (
            <button
              className={styles.recentThread}
              key={item.key}
              onClick={() => onSelectConversation(item.key)}
              type="button"
            >
              <span>{item.label}</span>
              <span>{threadMeta(item)}</span>
            </button>
          ))}
          {recentThreads.length === 0 ? <div className={styles.recentEmpty}>{locale.noRecentSessions}</div> : null}
        </div>
      </section>
    </div>
  );
}
