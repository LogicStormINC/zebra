import { createStyles } from "antd-style";

export const useConversationPaneStyle = createStyles(({ css }) => {
  return {
    main: css`
      min-width: 0;
      height: 100dvh;
      min-height: 0;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    `,
    topbar: css`
      height: var(--zebra-topbar-height);
      min-height: var(--zebra-topbar-height);
      flex: 0 0 auto;
      border-bottom: 1px solid var(--zebra-surface-border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 16px 0 24px;
      background: var(--zebra-page-background);
      z-index: 5;
      @media (max-width: 768px) {
        padding: 0 var(--zebra-space-xs);
      }
      @media (min-width: 1280px) {
        padding: 0 16px 0 24px;
      }
    `,
    titleWrap: css`
      min-width: 0;
      display: flex;
      align-items: center;
      gap: var(--zebra-space-sm);
    `,
    titleIcon: css`
      width: var(--zebra-icon-size);
      height: var(--zebra-icon-size);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 8px;
      background: var(--zebra-panel-soft-background);
      border: 1px solid var(--zebra-surface-border-soft);
      color: var(--zebra-text-muted);
    `,
    titleBlock: css`
      min-width: 0;
      display: flex;
      align-items: center;
      gap: var(--zebra-space-xs);
      h1 {
        margin: 0;
        font-size: 15px;
        line-height: 22px;
        font-weight: var(--zebra-font-weight-semibold);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      @media (max-width: 767px) {
        gap: var(--zebra-space-2xs);
      }
    `,
    titleMeta: css`
      color: var(--zebra-text-subtle);
      font-size: 12px;
      line-height: 18px;
      white-space: nowrap;
      @media (max-width: 767px) {
        display: none;
      }
    `,
    headerActions: css`
      display: flex;
      align-items: center;
      gap: var(--zebra-space-xs);
      flex: 0 0 auto;
    `,
    workspaceBadge: css`
      display: inline-flex;
      align-items: center;
      gap: var(--zebra-space-xs);
      height: 36px;
      padding: 0 var(--zebra-space-sm);
      border-radius: 10px;
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--zebra-surface-border);
      color: #d4d4d8;
      @media (max-width: 767px) {
        width: var(--zebra-icon-size-lg);
        padding: 0;
        justify-content: center;
        .ant-btn-icon + span {
          display: none;
        }
      }
    `,
    actionButton: css`
      background: transparent;
      border-color: var(--zebra-surface-border);
      color: var(--zebra-text-muted);
      height: 36px;
      &:hover {
        color: var(--zebra-text-primary) !important;
        border-color: rgba(255, 255, 255, 0.14) !important;
        background: rgba(255, 255, 255, 0.06) !important;
      }
    `,
    center: css`
      flex: 1;
      min-height: 0;
      display: flex;
      flex-direction: column;
      padding: 0 40px 40px 64px;
      overflow: hidden;
      @media (max-width: 768px) {
        padding: 0 var(--zebra-space-xs) var(--zebra-space-xs);
      }
      @media (min-width: 1280px) {
        padding: 0 40px 40px 64px;
      }
    `,
    stream: css`
      flex: 1;
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
      padding: 0 0 24px;
      overscroll-behavior: contain;
      @media (max-width: 768px) {
        padding: 20px 0 var(--zebra-space-sm);
      }
    `,
    streamInner: css`
      width: var(--zebra-pane-max);
      margin: 0 auto;
      position: relative;
      padding-left: 0;
      &::before {
        display: none;
      }
      @media (max-width: 767px) {
        padding-left: 0;
        &::before {
          display: none;
        }
      }
    `,
    idleWorkspace: css`
      width: min(840px, 100%);
      margin: 0 auto;
      padding-top: 112px;
      display: flex;
      flex-direction: column;
      align-items: stretch;
      gap: 16px;
      @media (max-height: 760px) {
        padding-top: 88px;
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
      font-size: 17px;
      line-height: 24px;
      font-weight: 600;
    `,
    idleSubtitle: css`
      margin-top: -8px;
      text-align: center;
      color: rgba(255, 255, 255, 0.52);
      font-size: 14px;
      line-height: 22px;
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
      box-shadow: var(--zebra-shadow-sm);
    `,
    composerDock: css`
      width: var(--zebra-content-max);
      margin: 0 auto;
      padding-top: 0;
      flex: 0 0 auto;
      max-width: 100%;
      @media (max-width: 768px) {
        padding-top: var(--zebra-space-xs);
      }
    `,
    composerCard: css`
      min-height: 96px;
      max-height: 240px;
      background: #1b1b1c;
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: var(--zebra-radius-composer);
      box-shadow: var(--zebra-shadow-lg);
      padding: var(--zebra-space-sm);
      overflow: hidden;
      @media (max-width: 768px) {
        border-radius: var(--zebra-radius-large);
        padding: var(--zebra-space-xs);
      }
    `,
    idleComposerCard: css`
      min-height: 156px;
      max-height: 260px;
      background: #1b1b1c;
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 22px;
      box-shadow: 0 18px 50px rgba(0, 0, 0, 0.32);
      padding: var(--zebra-space-sm);
      overflow: hidden;
    `,
    composerFooter: css`
      padding: 0 var(--zebra-space-xs) var(--zebra-space-xs);
      gap: 12px;
      @media (max-width: 767px) {
        .ant-flex:first-child {
          min-width: 0;
        }
      }
    `,
    composerTools: css`
      min-width: 0;
      overflow: hidden;
    `,
    modeSegment: css`
      height: 30px;
      display: inline-flex;
      align-items: center;
      gap: 2px;
      padding: 2px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.06);
      flex: 0 0 auto;
    `,
    modePill: css`
      display: inline-flex;
      align-items: center;
      justify-content: center;
      height: 26px;
      min-width: 42px;
      padding: 0 10px;
      border-radius: 999px;
      color: var(--zebra-text-muted);
      font-size: 12px;
      line-height: 18px;
      font-weight: 500;
    `,
    modePillActive: css`
      display: inline-flex;
      align-items: center;
      justify-content: center;
      height: 26px;
      min-width: 42px;
      padding: 0 10px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.08);
      color: var(--zebra-text-primary);
      font-size: 12px;
      line-height: 18px;
      font-weight: 500;
    `,
    toolbarButton: css`
      height: 30px;
      display: inline-flex;
      align-items: center;
      padding: 0 10px;
      border: 0;
      border-radius: 8px;
      background: transparent;
      color: rgba(255, 255, 255, 0.58);
      font: inherit;
      font-size: 12px;
      line-height: 18px;
      white-space: nowrap;
      cursor: pointer;
      transition: background 160ms ease, color 160ms ease;
      &:hover {
        background: rgba(255, 255, 255, 0.07);
        color: rgba(255, 255, 255, 0.82);
      }
      @media (max-width: 767px) {
        display: none;
      }
    `,
    sendSlot: css`
      flex: 0 0 auto;
      .ant-btn {
        transition: opacity 160ms ease, background 160ms ease, color 160ms ease;
      }
    `,
    sendSlotDisabled: css`
      pointer-events: none;
      .ant-btn {
        opacity: 0.45;
        background: rgba(255, 255, 255, 0.16) !important;
        color: rgba(255, 255, 255, 0.55) !important;
      }
    `,
    sender: css`
      .ant-sender {
        background: transparent;
        border: none;
        box-shadow: none;
      }
      .ant-sender-input,
      .ant-sender-textarea {
        color: var(--zebra-text-primary);
        font-size: 16px;
        line-height: 24px;
      }
      .ant-sender-input::placeholder,
      .ant-sender-textarea::placeholder {
        color: var(--zebra-text-subtle);
      }
      .ant-btn-color-primary.ant-btn-variant-solid {
        background: white;
        color: #111;
      }
      .ant-btn-color-primary.ant-btn-variant-solid:hover {
        background: #f4f4f4 !important;
        color: #111 !important;
      }
    `,
  };
});
