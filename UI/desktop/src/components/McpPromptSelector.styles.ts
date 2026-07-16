import { createStyles } from "antd-style";

export const useMcpPromptSelectorStyle = createStyles(({ css }) => ({
  root: css`
    display: grid;
    gap: 10px;
    padding-top: 10px;
    border-top: 1px solid rgba(255, 255, 255, 0.08);
  `,
  header: css`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    strong { font-size: 13px; font-weight: 600; }
  `,
  state: css`
    margin: 0;
    color: rgba(255, 255, 255, 0.5);
    font-size: 12px;
    line-height: 18px;
  `,
  error: css`
    margin: 0;
    color: #f0a25a;
    font-size: 12px;
    line-height: 18px;
  `,
  selected: css`
    display: grid;
    gap: 10px;
    padding: 10px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.025);
  `,
  description: css`
    margin: 0;
    color: rgba(255, 255, 255, 0.56);
    font-size: 12px;
    line-height: 18px;
  `,
  field: css`
    display: grid;
    gap: 5px;
    label {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      color: rgba(255, 255, 255, 0.72);
      font-size: 12px;
      line-height: 18px;
    }
    small { color: rgba(255, 255, 255, 0.38); font-size: 11px; }
  `,
  restored: css`
    display: grid;
    gap: 4px;
    padding: 9px 10px;
    border: 1px dashed rgba(255, 255, 255, 0.12);
    border-radius: 10px;
    code {
      overflow: hidden;
      color: rgba(255, 255, 255, 0.62);
      font-size: 11px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  `,
}));
