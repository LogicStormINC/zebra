import { createStyles } from "antd-style";

export const useTaskLaunchStyle = createStyles(({ css }) => ({
  summary: css`
    min-width: 0;
    min-height: 28px;
    padding: 0 var(--zebra-space-sm) var(--zebra-space-xs);
    display: flex;
    align-items: center;
    gap: var(--zebra-space-sm);
    color: rgba(255, 255, 255, 0.48);
    font-size: 12px;
    line-height: 18px;
    white-space: nowrap;
    overflow: hidden;
    strong { color: rgba(255, 255, 255, 0.76); font-weight: 600; }
    span { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
    em { color: #f0a25a; font-style: normal; }
    @media (max-width: 767px) { span:nth-of-type(3) { display: none; } }
  `,
  editor: css`
    width: min(360px, calc(100vw - 40px));
    display: flex;
    flex-direction: column;
    gap: var(--zebra-space-sm);
    strong { font-size: 13px; }
    span { color: rgba(255, 255, 255, 0.5); font-size: 12px; line-height: 18px; }
    .ant-checkbox-group { display: grid; gap: 8px; }
  `,
  staticBadge: css`
    height: 30px;
    display: inline-flex;
    align-items: center;
    padding: 0 10px;
    color: rgba(255, 255, 255, 0.44);
    font-size: 12px;
    line-height: 18px;
    white-space: nowrap;
    @media (max-width: 767px) { display: none; }
  `,
}));
