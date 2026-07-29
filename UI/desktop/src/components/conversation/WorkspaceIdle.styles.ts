import { createStyles } from "antd-style";

export const useWorkspaceIdleStyle = createStyles(({ css }) => ({
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
}));
