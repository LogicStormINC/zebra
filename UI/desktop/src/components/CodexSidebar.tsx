import {
  AppstoreOutlined,
  ClockCircleOutlined,
  CodeOutlined,
  DeleteOutlined,
  EditOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { Button, Tooltip } from "antd";
import { createStyles } from "antd-style";
import { clsx } from "clsx";
import locale from "../_utils/local";
import type { ConversationSeed } from "../lib/chat-surface";
import type { SessionSummary } from "../types";

const useStyle = createStyles(({ css }) => {
  return {
    sidebar: css`
      background: rgba(31, 31, 31, 0.92);
      border-right: 1px solid rgba(255, 255, 255, 0.08);
      width: 100%;
      padding: var(--zebra-space-md) var(--zebra-space-sm) calc(var(--zebra-space-sm) * 0.9);
      display: flex;
      flex-direction: column;
      min-height: 100vh;
      backdrop-filter: blur(20px);
      @media (max-width: 1019px) {
        min-height: auto;
        border-right: none;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        padding-bottom: var(--zebra-space-sm);
      }
    `,
    sidebarTop: css`
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-2xs);
      margin-bottom: var(--zebra-space-md);
    `,
    navButton: css`
      display: flex;
      align-items: center;
      gap: var(--zebra-space-sm);
      width: 100%;
      background: transparent;
      border: none;
      color: rgba(255, 255, 255, 0.92);
      border-radius: var(--zebra-radius-soft);
      padding: var(--zebra-space-xs) var(--zebra-space-sm);
      text-align: left;
      font-size: var(--zebra-font-size-sm);
      font-weight: var(--zebra-font-weight-medium);
      cursor: pointer;
      transition: background 160ms ease, color 160ms ease;
      &:hover {
        background: rgba(255, 255, 255, 0.06);
      }
    `,
    staticNav: css`
      cursor: default;
      color: rgba(255, 255, 255, 0.82);
    `,
    navIcon: css`
      width: var(--zebra-icon-size-xs);
      display: inline-flex;
      justify-content: center;
      color: rgba(255, 255, 255, 0.72);
    `,
    section: css`
      margin-top: var(--zebra-space-xs);
    `,
    sectionTitle: css`
      padding: var(--zebra-space-xs) var(--zebra-space-sm) calc(var(--zebra-space-xs) - var(--zebra-space-3xs));
      color: rgba(255, 255, 255, 0.45);
      font-size: var(--zebra-font-size-sm);
      font-weight: 600;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    `,
    conversationList: css`
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-2xs);
    `,
    conversationItem: css`
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
      gap: var(--zebra-space-sm);
      padding: var(--zebra-space-xs) var(--zebra-space-sm);
      border-radius: var(--zebra-radius-soft);
      color: rgba(255, 255, 255, 0.74);
      transition: background 160ms ease, color 160ms ease;
      cursor: pointer;
      &:hover {
        background: rgba(255, 255, 255, 0.05);
        color: rgba(255, 255, 255, 0.96);
      }
      &:hover .codex-delete-button {
        opacity: 1;
      }
    `,
    conversationItemActive: css`
      background: rgba(255, 255, 255, 0.1);
      color: rgba(255, 255, 255, 0.96);
      .codex-delete-button {
        opacity: 1;
      }
    `,
    conversationMain: css`
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-2xs);
    `,
    conversationLabel: css`
      display: flex;
      align-items: center;
      gap: var(--zebra-space-xs);
      min-width: 0;
      font-size: var(--zebra-font-size-md);
      font-weight: var(--zebra-font-weight-medium);
    `,
    conversationText: css`
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      min-width: 0;
    `,
    conversationMeta: css`
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--zebra-space-xs);
      color: rgba(255, 255, 255, 0.42);
      font-size: var(--zebra-font-size-xs);
    `,
    statusDot: css`
      width: var(--zebra-icon-dot);
      height: var(--zebra-icon-dot);
      border-radius: 50%;
      flex: 0 0 auto;
      background: rgba(255, 255, 255, 0.34);
    `,
    statusReady: css`
      background: #6aa2ff;
    `,
    statusCompleted: css`
      background: #31c48d;
    `,
    statusFailed: css`
      background: #f87171;
    `,
    statusRunning: css`
      background: #f59e0b;
      box-shadow: var(--zebra-shadow-running);
    `,
    sessionMetaRight: css`
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    `,
    deleteButton: css`
      opacity: 0;
      transition: opacity 160ms ease;
    `,
    projectCard: css`
      display: flex;
      align-items: center;
      gap: var(--zebra-space-xs);
      padding: var(--zebra-space-sm);
      border-radius: var(--zebra-radius-soft);
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.05);
      color: rgba(255, 255, 255, 0.92);
    `,
    projectIcon: css`
      width: var(--zebra-icon-size-sm);
      height: var(--zebra-icon-size-sm);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: var(--zebra-radius-xs);
      background: rgba(242, 140, 56, 0.16);
      color: #ffbc82;
      font-size: var(--zebra-font-size-md);
    `,
    projectMeta: css`
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-3xs);
      span:last-child {
        color: rgba(255, 255, 255, 0.45);
        font-size: var(--zebra-font-size-xs);
      }
    `,
    profile: css`
      margin-top: auto;
      padding-top: var(--zebra-space-sm);
      border-top: 1px solid rgba(255, 255, 255, 0.05);
      display: flex;
      align-items: center;
      gap: var(--zebra-space-sm);
    `,
    avatar: css`
      width: var(--zebra-icon-size-lg);
      height: var(--zebra-icon-size-lg);
      border-radius: 50%;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(135deg, #525252, #2d2d2d);
      color: white;
      font-weight: 700;
    `,
    profileMeta: css`
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-3xs);
      span:last-child {
        color: rgba(255, 255, 255, 0.45);
        font-size: var(--zebra-font-size-xs);
      }
    `,
  };
});

interface CodexSidebarProps {
  conversations: ConversationSeed[];
  conversationSessionIds: Record<string, string>;
  currentConversation: string;
  onCreateConversation: () => void;
  onDeleteConversation: (key: string) => void;
  onSelectConversation: (key: string) => void;
  sessionSummaries: Record<string, SessionSummary | null>;
}

function groupConversations(conversations: ConversationSeed[]) {
  const pinned = conversations.filter((item) => item.group === locale.pinned);
  const recent = conversations.filter((item) => item.group !== locale.pinned);
  return { pinned, recent };
}

function ConversationSection({
  currentConversation,
  conversationSessionIds,
  items,
  onDeleteConversation,
  onSelectConversation,
  sessionSummaries,
}: {
  currentConversation: string;
  conversationSessionIds: Record<string, string>;
  items: ConversationSeed[];
  onDeleteConversation: (key: string) => void;
  onSelectConversation: (key: string) => void;
  sessionSummaries: Record<string, SessionSummary | null>;
}) {
  const { styles } = useStyle();

  if (items.length === 0) {
    return (
      <div className={styles.conversationItem}>
        <div className={styles.conversationMain}>
          <div className={styles.conversationLabel}>{locale.noRecentSessions}</div>
          <div className={styles.conversationMeta}>{locale.recentHint}</div>
        </div>
      </div>
    );
  }

  return (
    <>
      {items.map((item) => {
        const isActive = item.key === currentConversation;
        const summary = sessionSummaries[item.key];
        const sessionId = conversationSessionIds[item.key];
        const status = summary?.status ?? "draft";
        return (
          <div
            className={clsx(styles.conversationItem, isActive && styles.conversationItemActive)}
            key={item.key}
            onClick={() => {
              onSelectConversation(item.key);
            }}
          >
            <div className={styles.conversationMain}>
              <div className={styles.conversationLabel}>
                <span
                  className={clsx(
                    styles.statusDot,
                    status === "ready" && styles.statusReady,
                    status === "completed" && styles.statusCompleted,
                    status === "failed" && styles.statusFailed,
                    status === "running" && styles.statusRunning,
                  )}
                />
                <span className={styles.conversationText}>{item.label}</span>
              </div>
              <div className={styles.conversationMeta}>
                <span>{status}</span>
                <span className={styles.sessionMetaRight}>{sessionId ? sessionId.slice(0, 6) : item.group}</span>
              </div>
            </div>
            <Tooltip title={locale.delete}>
              <Button
                className={clsx("codex-delete-button", styles.deleteButton)}
                icon={<DeleteOutlined />}
                onClick={(event) => {
                  event.stopPropagation();
                  onDeleteConversation(item.key);
                }}
                size="small"
                type="text"
              />
            </Tooltip>
          </div>
        );
      })}
    </>
  );
}

export function CodexSidebar({
  conversations,
  conversationSessionIds,
  currentConversation,
  onCreateConversation,
  onDeleteConversation,
  onSelectConversation,
  sessionSummaries,
}: CodexSidebarProps) {
  const { styles } = useStyle();
  const { pinned, recent } = groupConversations(conversations);

  return (
    <aside className={styles.sidebar}>
      <div className={styles.sidebarTop}>
        <button className={styles.navButton} onClick={onCreateConversation} type="button">
          <span className={styles.navIcon}>
            <EditOutlined />
          </span>
          <span>{locale.newConversation}</span>
        </button>
        <div className={clsx(styles.navButton, styles.staticNav)}>
          <span className={styles.navIcon}>
            <SearchOutlined />
          </span>
          <span>{locale.search}</span>
        </div>
        <div className={clsx(styles.navButton, styles.staticNav)}>
          <span className={styles.navIcon}>
            <ClockCircleOutlined />
          </span>
          <span>{locale.scheduled}</span>
        </div>
        <div className={clsx(styles.navButton, styles.staticNav)}>
          <span className={styles.navIcon}>
            <AppstoreOutlined />
          </span>
          <span>{locale.plugins}</span>
        </div>
      </div>

      <section className={styles.section}>
        <div className={styles.sectionTitle}>{locale.pinned}</div>
        <div className={styles.conversationList}>
          <ConversationSection
            conversationSessionIds={conversationSessionIds}
            currentConversation={currentConversation}
            items={pinned}
            onDeleteConversation={onDeleteConversation}
            onSelectConversation={onSelectConversation}
            sessionSummaries={sessionSummaries}
          />
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionTitle}>{locale.recent}</div>
        <div className={styles.conversationList}>
          <ConversationSection
            conversationSessionIds={conversationSessionIds}
            currentConversation={currentConversation}
            items={recent}
            onDeleteConversation={onDeleteConversation}
            onSelectConversation={onSelectConversation}
            sessionSummaries={sessionSummaries}
          />
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionTitle}>{locale.projects}</div>
        <div className={styles.projectCard}>
          <span className={styles.projectIcon}>
            <CodeOutlined />
          </span>
          <div className={styles.projectMeta}>
            <span>zebra-agent</span>
            <span>{locale.projectHint}</span>
          </div>
        </div>
      </section>

      <div className={styles.profile}>
        <span className={styles.avatar}>ZA</span>
        <div className={styles.profileMeta}>
          <span>{locale.profileName}</span>
          <span>{locale.profilePlan}</span>
        </div>
      </div>
    </aside>
  );
}
