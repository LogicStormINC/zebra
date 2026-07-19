import { createStyles } from "antd-style";

export const useComposerAttachmentsStyle = createStyles(({ css }) => ({
  surface: css`
    display: flex;
    align-items: center;
    gap: 6px;
    overflow-x: auto;
    padding: 0;
    flex: 0 1 auto;
  `,
  fileInput: css`
    display: none;
  `,
  attachButton: css`
    width: 30px;
    height: 30px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 0;
    border-radius: 8px;
    background: transparent;
    color: rgba(255, 255, 255, 0.58);
    cursor: pointer;
    flex: 0 0 auto;
    &:hover:not(:disabled) {
      background: rgba(255, 255, 255, 0.07);
      color: rgba(255, 255, 255, 0.85);
    }
    &:disabled { opacity: 0.45; cursor: not-allowed; }
  `,
  chip: css`
    min-width: 0;
    max-width: 240px;
    height: 30px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 0 8px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.05);
    color: rgba(255, 255, 255, 0.75);
    font-size: 12px;
    flex: 0 0 auto;
    > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    small { color: rgba(255, 255, 255, 0.4); white-space: nowrap; }
    button {
      border: 0;
      background: transparent;
      color: rgba(255, 255, 255, 0.5);
      cursor: pointer;
      padding: 0 2px;
    }
  `,
  error: css`
    color: #f0a2a2;
    font-size: 12px;
    line-height: 18px;
    white-space: nowrap;
  `,
}));
