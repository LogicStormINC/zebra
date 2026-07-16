import { createStyles } from "antd-style";

export const useSessionThreadWorkspaceStyle = createStyles(({ css }) => ({
  workspace: css`
    width: min(1120px, 100%);
    margin: 0 auto;
    padding: 24px 0;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 280px;
    gap: 22px;
    @media (max-width: 1020px) {
      grid-template-columns: 1fr;
    }
  `,
  timeline: css`
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 14px;
  `,
  taskCard: css`
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    padding: 4px 2px 14px;
    h2 {
      margin: 3px 0 2px;
      color: var(--zebra-text-primary);
      font-size: 17px;
      line-height: 25px;
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
    letter-spacing: 0.07em;
    text-transform: uppercase;
  `,
  currentStatus: css`
    color: rgba(255, 255, 255, 0.62);
  `,
  eventStream: css`
    display: flex;
    flex-direction: column;
    gap: 16px;
    min-width: 0;
  `,
  userWrap: css`
    display: flex;
    justify-content: flex-end;
  `,
  userCard: css`
    max-width: min(78%, var(--zebra-content-card-max));
    padding: 9px 13px;
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.07);
    border: 1px solid rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.88);
    font-size: 14px;
    line-height: 22px;
    overflow-wrap: anywhere;
    white-space: pre-wrap;
  `,
  statusRow: css`
    min-width: 0;
    display: grid;
    grid-template-columns: 8px minmax(0, 1fr) auto;
    align-items: center;
    gap: 8px;
    padding: 0 8px;
    color: rgba(255, 255, 255, 0.6);
    font-size: 12px;
    line-height: 19px;
    span:nth-child(2) {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    span:last-child {
      color: rgba(255, 255, 255, 0.46);
      white-space: nowrap;
    }
  `,
  statusMarker: css`
    width: 4px;
    height: 4px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.44);
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
    grid-template-columns: repeat(2, 1fr);
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
