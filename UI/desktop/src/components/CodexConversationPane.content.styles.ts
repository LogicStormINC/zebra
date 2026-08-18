import type { CssUtil } from "antd-style";

export function conversationPaneContentStyles(css: CssUtil) {
  return {
    idleWorkspace: css`
      width: min(860px, 100%);
      margin: 0 auto;
      padding-top: 104px;
      display: flex;
      flex-direction: column;
      align-items: stretch;
      gap: 14px;
      @media (max-height: 760px) {
        padding-top: 82px;
      }
      @media (max-width: 768px) {
        padding-top: 32px;
      }
    `,
    projectContext: css`
      text-align: center;
      display: flex;
      flex-direction: column;
      gap: 2px;
    `,
    projectName: css`
      color: var(--zebra-text-primary);
      font-size: 15px;
      line-height: 22px;
      font-weight: 600;
    `,
    projectMeta: css`
      color: var(--zebra-text-muted);
      font-size: 12px;
      line-height: 18px;
    `,
    idleQuestion: css`
      margin: 0;
      text-align: center;
      color: var(--zebra-text-primary);
      font-size: 20px;
      line-height: 28px;
      font-weight: 600;
    `,
    idleSubtitle: css`
      margin-top: -6px;
      text-align: center;
      color: rgba(255, 255, 255, 0.52);
      font-size: 13px;
      line-height: 20px;
    `,
    envCard: css`
      border: 1px solid var(--zebra-surface-border);
      border-radius: 16px;
      background: var(--zebra-panel-soft-background);
      padding: 12px 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    `,
    envCardHeader: css`
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    `,
    envCardTitle: css`
      color: var(--zebra-text-muted);
      font-size: 12px;
      line-height: 18px;
      font-weight: 600;
      letter-spacing: 0.02em;
    `,
    envCardMeta: css`
      color: var(--zebra-text-subtle);
      font-size: 11px;
      line-height: 16px;
    `,
    envGrid: css`
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      @media (max-width: 768px) {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    `,
    envCell: css`
      min-width: 0;
      display: flex;
      align-items: flex-start;
      gap: 8px;
      padding: 8px 10px;
      border-radius: 10px;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid var(--zebra-surface-border-soft);
    `,
    envCellIcon: css`
      flex: 0 0 auto;
      width: 26px;
      height: 26px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.05);
      color: var(--zebra-text-muted);
      font-size: 14px;
    `,
    envCellBody: css`
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 1px;
    `,
    envCellLabel: css`
      color: var(--zebra-text-subtle);
      font-size: 11px;
      line-height: 16px;
    `,
    envCellValue: css`
      color: var(--zebra-text-primary);
      font-size: 13px;
      line-height: 18px;
      font-weight: 500;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    `,
    envError: css`
      color: #f87171;
      font-size: 12px;
      line-height: 18px;
      margin-top: 2px;
    `,
    envHint: css`
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 6px 12px;
      padding: 8px 12px;
      margin-bottom: 12px;
      border: 1px solid var(--zebra-surface-border-soft);
      border-radius: 10px;
      background: rgba(255, 255, 255, 0.02);
      color: var(--zebra-text-muted);
      font-size: 12px;
      line-height: 18px;
      span {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        min-width: 0;
      }
      span > .anticon {
        color: var(--zebra-text-subtle);
      }
      span > b {
        color: var(--zebra-text-primary);
        font-weight: 500;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 240px;
      }
    `,
    idleSection: css`
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding-top: 8px;
    `,
    idleSectionTitle: css`
      color: var(--zebra-text-muted);
      font-size: 13px;
      line-height: 20px;
      font-weight: 600;
    `,
    actionGrid: css`
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    `,
    quickAction: css`
      height: 36px;
      display: inline-flex;
      align-items: center;
      padding: 0 16px;
      border-radius: var(--zebra-radius-pill);
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid var(--zebra-surface-border);
      color: #d4d4d8;
      font-size: 14px;
      line-height: 22px;
      font-family: inherit;
      cursor: pointer;
      transition: background 160ms ease, border-color 160ms ease;
      &:hover {
        background: rgba(255, 255, 255, 0.1);
        border-color: rgba(255, 255, 255, 0.12);
      }
      &:disabled {
        cursor: not-allowed;
        opacity: 0.45;
      }
    `,
    recentGroup: css`
      color: var(--zebra-text-muted);
      font-size: 12px;
      line-height: 18px;
    `,
    recentList: css`
      display: flex;
      flex-direction: column;
      gap: 4px;
    `,
    recentThread: css`
      width: 100%;
      min-height: 52px;
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: 2px;
      padding: 0 12px;
      border: 0;
      border-radius: 10px;
      background: transparent;
      color: var(--zebra-text-primary);
      font-family: inherit;
      font-size: 14px;
      line-height: 22px;
      text-align: left;
      cursor: pointer;
      span:first-child {
        min-width: 0;
        overflow: hidden;
        white-space: nowrap;
        text-overflow: ellipsis;
      }
      span:last-child {
        color: rgba(255, 255, 255, 0.42);
        font-size: 12px;
        line-height: 18px;
      }
      &:hover {
        background: rgba(255, 255, 255, 0.05);
      }
    `,
    recentEmpty: css`
      color: var(--zebra-text-muted);
      font-size: 14px;
      line-height: 22px;
      padding: 6px 10px;
    `,
  };
}
