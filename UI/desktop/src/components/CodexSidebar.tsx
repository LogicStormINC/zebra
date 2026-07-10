import {
  CodeOutlined,
  DeleteOutlined,
  EditOutlined,
} from "@ant-design/icons";
import { Button, Tooltip } from "antd";
import { createStyles } from "antd-style";
import { clsx } from "clsx";
import locale from "../_utils/local";
import { sessionStatusLabel, sessionWorkspaceLabel } from "../_utils/session-status";
import type { ConversationSeed } from "../lib/chat-surface";
import type { SessionSummary } from "../types";
const useStyle = createStyles(({ css }) => ({
    sidebar: css`
      background: #181818;
      border-right: 1px solid var(--zebra-surface-border);
      width: 100%;
      padding: var(--zebra-space-sm);
      display: flex;
      flex-direction: column;
      height: 100dvh;
      min-height: 0;
      overflow: hidden;
      @media (max-width: 767px) {
        padding: var(--zebra-space-sm) var(--zebra-space-xs);
      }
    `,
    sidebarTop: css`
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-2xs);
      margin-bottom: var(--zebra-space-sm);
      flex: 0 0 auto;
      @media (max-width: 767px) {
        align-items: center;
        margin-bottom: var(--zebra-space-sm);
      }
    `,
    navButton: css`
      display: flex;
      align-items: center;
      gap: var(--zebra-space-sm);
      width: 100%;
      height: 42px;
      background: transparent;
      border: none;
      color: var(--zebra-text-primary);
      border-radius: 10px;
      padding: 0 var(--zebra-space-sm);
      text-align: left;
      font-size: 14px;
      line-height: 22px;
      font-weight: var(--zebra-font-weight-medium);
      cursor: pointer;
      transition: background 160ms ease, color 160ms ease;
      &:hover {
        background: rgba(255, 255, 255, 0.06);
      }
      @media (max-width: 767px) {
        justify-content: center;
        padding: var(--zebra-space-xs);
        span:last-child {
          display: none;
        }
      }
    `,
    navIcon: css`
      width: var(--zebra-icon-size-xs);
      display: inline-flex;
      justify-content: center;
      color: var(--zebra-text-muted);
    `,
    section: css`
      margin-top: var(--zebra-space-xs);
      min-width: 0;
      @media (max-width: 767px) {
        margin-top: var(--zebra-space-2xs);
      }
    `,
    sectionTitle: css`
      padding: var(--zebra-space-xs) var(--zebra-space-sm) calc(var(--zebra-space-xs) - var(--zebra-space-3xs));
      color: var(--zebra-text-subtle);
      font-size: 12px;
      line-height: 18px;
      font-weight: var(--zebra-font-weight-medium);
      letter-spacing: 0.05em;
      text-transform: uppercase;
      @media (max-width: 767px) {
        display: none;
      }
    `,
    sidebarScroll: css`
      min-height: 0;
      flex: 1 1 auto;
      overflow-y: auto;
      overflow-x: hidden;
      padding-right: 2px;
      scrollbar-width: thin;
      scrollbar-color: var(--zebra-sidebar-track) transparent;
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
      min-height: 52px;
      padding: 6px var(--zebra-space-sm);
      border-radius: 10px;
      color: #d4d4d8;
      transition: background 160ms ease, color 160ms ease;
      cursor: pointer;
      &:hover {
        background: rgba(255, 255, 255, 0.06);
        color: var(--zebra-text-primary);
      }
      &:hover .codex-delete-button {
        opacity: 1;
      }
      @media (max-width: 767px) {
        grid-template-columns: 1fr;
        justify-items: center;
        gap: 0;
        padding: var(--zebra-space-xs);
      }
    `,
    conversationItemActive: css`
      background: rgba(255, 255, 255, 0.075);
      color: var(--zebra-text-primary);
    `,
    conversationMain: css`
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-2xs);
      @media (max-width: 767px) {
        align-items: center;
      }
    `,
    conversationLabel: css`
      display: flex;
      align-items: center;
      gap: var(--zebra-space-xs);
      min-width: 0;
      font-size: 14px;
      line-height: 22px;
      font-weight: var(--zebra-font-weight-medium);
      @media (max-width: 767px) {
        justify-content: center;
      }
    `,
    conversationText: css`
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      min-width: 0;
      @media (max-width: 767px) {
        display: none;
      }
    `,
    conversationMeta: css`
      color: var(--zebra-text-subtle);
      font-size: 12px;
      line-height: 18px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      @media (max-width: 767px) {
        display: none;
      }
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
    deleteButton: css`
      opacity: 0;
      transition: opacity 160ms ease;
      @media (max-width: 767px) {
        display: none;
      }
    `,
    projectCard: css`
      width: 100%;
      display: flex;
      align-items: center;
      gap: var(--zebra-space-xs);
      padding: var(--zebra-space-sm);
      border-radius: 10px;
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--zebra-surface-border-soft);
      color: var(--zebra-text-primary);
      font: inherit;
      text-align: left;
      cursor: pointer;
      transition: background 160ms ease, border-color 160ms ease;
      &:hover {
        background: rgba(255, 255, 255, 0.055);
      }
    `,
    projectCardActive: css`
      background: rgba(255, 255, 255, 0.075);
      border-color: transparent;
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
        color: var(--zebra-text-subtle);
        font-size: 12px;
        line-height: 18px;
      }
      @media (max-width: 767px) {
        display: none;
      }
    `,
    profile: css`
      flex: 0 0 auto;
      padding-top: var(--zebra-space-sm);
      border-top: 1px solid var(--zebra-surface-border-soft);
      display: flex;
      align-items: center;
      gap: var(--zebra-space-sm);
      @media (max-width: 767px) {
        justify-content: center;
        padding-top: var(--zebra-space-xs);
      }
    `,
    avatar: css`
      width: var(--zebra-icon-size-lg);
      height: var(--zebra-icon-size-lg);
      border-radius: 50%;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: #27272a;
      color: white;
      font-weight: 600;
    `,
    profileMeta: css`
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-3xs);
      span:last-child {
        color: var(--zebra-text-subtle);
        font-size: 12px;
        line-height: 18px;
      }
      @media (max-width: 767px) {
        display: none;
      }
    `,
}));
interface CodexSidebarProps {
  conversations: ConversationSeed[];
  currentConversation: string;
  isWorkspaceIdle: boolean;
  onCreateConversation: () => void;
  onDeleteConversation: (key: string) => void;
  onSelectConversation: (key: string) => void;
  projectMeta: string;
  runtimeLabel: string;
  sessionSummaries: Record<string, SessionSummary | null>;
}

function groupConversations(conversations: ConversationSeed[]) {
  const pinned = conversations.filter((item) => item.group === locale.pinned);
  const recent = conversations.filter((item) => item.group !== locale.pinned);
  return { pinned, recent };
}

function threadMeta(summary: SessionSummary | null | undefined, group: string): string {
  const dayLabel = group === locale.pinned ? locale.todayGroup : group;
  return `${sessionStatusLabel(summary?.status)} · ${dayLabel} · ${sessionWorkspaceLabel(summary)}`;
}

function ConversationSection({
  currentConversation,
  isWorkspaceIdle,
  items,
  onDeleteConversation,
  onSelectConversation,
  sessionSummaries,
}: {
  currentConversation: string;
  isWorkspaceIdle: boolean;
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
        const isActive = !isWorkspaceIdle && item.key === currentConversation;
        const summary = sessionSummaries[item.key];
        const status = summary?.status ?? "draft";
        return (
          <div
            className={clsx(styles.conversationItem, isActive && styles.conversationItemActive)}
            key={item.key}
            onClick={() => {
              onSelectConversation(item.key);
            }}
            onKeyDown={(event) => {
              if (event.key !== "Enter" && event.key !== " ") {
                return;
              }
              event.preventDefault();
              onSelectConversation(item.key);
            }}
            role="button"
            tabIndex={0}
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
              <div className={styles.conversationMeta}>{threadMeta(summary, item.group)}</div>
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
  currentConversation,
  isWorkspaceIdle,
  onCreateConversation,
  onDeleteConversation,
  onSelectConversation,
  projectMeta,
  runtimeLabel,
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
      </div>

      <div className={styles.sidebarScroll}>
        {pinned.length > 0 ? (
          <section className={styles.section}>
            <div className={styles.sectionTitle}>{locale.pinned}</div>
            <div className={styles.conversationList}>
              <ConversationSection
                currentConversation={currentConversation}
                isWorkspaceIdle={isWorkspaceIdle}
                items={pinned}
                onDeleteConversation={onDeleteConversation}
                onSelectConversation={onSelectConversation}
                sessionSummaries={sessionSummaries}
              />
            </div>
          </section>
        ) : null}

        <section className={styles.section}>
          <div className={styles.sectionTitle}>{locale.recent}</div>
          <div className={styles.conversationList}>
            <ConversationSection
              currentConversation={currentConversation}
              isWorkspaceIdle={isWorkspaceIdle}
              items={recent}
              onDeleteConversation={onDeleteConversation}
              onSelectConversation={onSelectConversation}
              sessionSummaries={sessionSummaries}
            />
          </div>
        </section>

        <section className={styles.section}>
          <div className={styles.sectionTitle}>{locale.projects}</div>
          <button
            className={clsx(styles.projectCard, isWorkspaceIdle && styles.projectCardActive)}
            onClick={onCreateConversation}
            type="button"
          >
            <span className={styles.projectIcon}>
              <CodeOutlined />
            </span>
            <div className={styles.projectMeta}>
              <span>zebra-agent</span>
              <span>{projectMeta}</span>
            </div>
          </button>
        </section>
      </div>

      <div className={styles.profile}>
        <span className={styles.avatar}>ZA</span>
        <div className={styles.profileMeta}>
          <span>{locale.profileName}</span>
          <span>{runtimeLabel}</span>
        </div>
      </div>
    </aside>
  );
}
