import { createStyles } from "antd-style";

export const useSessionThreadWorkspaceStyle = createStyles(({ css }) => ({
  workspace: css`
    width: min(1120px, 100%);
    margin: 0 auto;
    padding: 32px 0 24px;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 280px;
    gap: 24px;
    @media (max-width: 1020px) {
      grid-template-columns: 1fr;
    }
  `,
  timeline: css`
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 16px;
  `,
  taskCard: css`
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.035);
    padding: 18px 20px;
    h2 {
      margin: 6px 0 4px;
      color: var(--zebra-text-primary);
      font-size: 18px;
      line-height: 26px;
      font-weight: 600;
    }
    p {
      margin: 0;
      color: var(--zebra-text-muted);
      font-size: 13px;
      line-height: 20px;
    }
  `,
  eyebrow: css`
    color: rgba(245, 158, 11, 0.92);
    font-size: 12px;
    line-height: 18px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  `,
  stageList: css`
    display: flex;
    flex-direction: column;
    padding: 2px 0 2px 4px;
  `,
  stage: css`
    min-height: 52px;
    display: grid;
    grid-template-columns: 22px minmax(0, 1fr) auto;
    align-items: center;
    gap: 10px;
    position: relative;
    color: rgba(255, 255, 255, 0.44);
    &::before {
      content: "";
      position: absolute;
      left: 10px;
      top: 36px;
      bottom: -16px;
      width: 1px;
      background: rgba(255, 255, 255, 0.08);
    }
    &:last-child::before {
      display: none;
    }
  `,
  stageActive: css`
    color: var(--zebra-text-primary);
  `,
  stageDone: css`
    color: rgba(255, 255, 255, 0.76);
  `,
  stageDot: css`
    width: 22px;
    height: 22px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    background: #202021;
    border: 1px solid rgba(255, 255, 255, 0.1);
    color: rgba(255, 255, 255, 0.46);
    font-size: 11px;
    z-index: 1;
  `,
  stageDotActive: css`
    border-color: rgba(245, 158, 11, 0.5);
    color: #f5a623;
    box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.08);
  `,
  stageDotDone: css`
    background: rgba(255, 255, 255, 0.1);
    color: rgba(255, 255, 255, 0.82);
  `,
  stageText: css`
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
    strong {
      font-size: 13px;
      line-height: 20px;
      font-weight: 500;
    }
    span {
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      color: rgba(255, 255, 255, 0.4);
      font-size: 12px;
      line-height: 18px;
    }
  `,
  stageMeta: css`
    color: rgba(255, 255, 255, 0.34);
    font-size: 11px;
    white-space: nowrap;
  `,
  messageStack: css`
    display: flex;
    flex-direction: column;
    gap: var(--zebra-space-lg);
  `,
  userWrap: css`
    display: flex;
    justify-content: flex-end;
  `,
  userCard: css`
    max-width: var(--zebra-content-card-max);
    padding: var(--zebra-space-md) var(--zebra-space-lg);
    border-radius: var(--zebra-radius-large);
    background: var(--zebra-panel-soft-background);
    border: 1px solid var(--zebra-surface-border);
    color: var(--zebra-text-primary);
    font-size: 14px;
    line-height: 22px;
  `,
  inspector: css`
    min-width: 0;
    align-self: start;
    position: sticky;
    top: 24px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.025);
    overflow: hidden;
    @media (max-width: 1020px) {
      position: static;
    }
  `,
  inspectorTabs: css`
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 2px;
    padding: 6px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.07);
  `,
  inspectorTab: css`
    height: 30px;
    padding: 0 4px;
    border: 0;
    border-radius: 8px;
    background: transparent;
    color: rgba(255, 255, 255, 0.46);
    font: inherit;
    font-size: 11px;
    cursor: pointer;
    &:hover {
      background: rgba(255, 255, 255, 0.05);
      color: rgba(255, 255, 255, 0.72);
    }
  `,
  inspectorTabActive: css`
    background: rgba(255, 255, 255, 0.08);
    color: var(--zebra-text-primary);
  `,
  inspectorBody: css`
    min-height: 210px;
    padding: 14px;
    h3 {
      margin: 0 0 12px;
      color: var(--zebra-text-primary);
      font-size: 13px;
      line-height: 20px;
      font-weight: 600;
    }
  `,
  inspectorList: css`
    display: flex;
    flex-direction: column;
    gap: 10px;
  `,
  inspectorRow: css`
    min-width: 0;
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 10px;
    color: rgba(255, 255, 255, 0.62);
    font-size: 12px;
    line-height: 18px;
    span:first-child {
      color: rgba(255, 255, 255, 0.38);
      flex: 0 0 auto;
    }
    span:last-child {
      min-width: 0;
      overflow: hidden;
      text-align: right;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  `,
  logRow: css`
    display: flex;
    flex-direction: column;
    gap: 1px;
    padding-bottom: 8px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    color: rgba(255, 255, 255, 0.64);
    font-size: 12px;
    line-height: 18px;
    span:last-child {
      color: rgba(255, 255, 255, 0.34);
      font-size: 11px;
    }
  `,
  empty: css`
    margin: 0;
    color: rgba(255, 255, 255, 0.38);
    font-size: 12px;
    line-height: 18px;
  `,
}));
