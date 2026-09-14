import { createStyles } from "antd-style";
import { conversationPaneContentStyles } from "./CodexConversationPane.content.styles";

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
      padding: 0 30px 40px;
      overflow: hidden;
      @media (max-width: 768px) {
        padding: 0 var(--zebra-space-xs) var(--zebra-space-xs);
      }
      @media (min-width: 1280px) {
        padding: 0 40px 40px 56px;
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
    ...conversationPaneContentStyles(css),
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
      max-height: min(240px, 42dvh);
      background: #202021;
      border: 1px solid rgba(255, 255, 255, 0.11);
      border-radius: 20px;
      box-shadow: 0 14px 40px rgba(0, 0, 0, 0.3);
      padding: 8px;
      overflow: hidden;
      .ant-sender {
        display: flex;
        flex-direction: column;
      }
      .ant-sender-content {
        flex: 1;
      }
      .ant-sender-footer {
        flex: 0 0 auto;
      }
      @media (max-width: 768px) {
        border-radius: 16px;
        padding: 6px;
      }
    `,
    composerFooter: css`
      width: 100%;
      min-height: 38px;
      padding: 2px 4px 0;
      gap: 8px;
      @media (max-width: 767px) {
        .ant-flex:first-child {
          min-width: 0;
        }
      }
    `,
    composerActions: css`
      min-width: 0;
      overflow: visible;
    `,
    composerTools: css`
      min-width: 0;
      flex: 0 1 auto;
    `,
    composerRuntime: css`
      min-width: 0;
      flex: 0 1 auto;
    `,
    runtimeControls: css`
      display: inline-flex;
      align-items: center;
      gap: 4px;
      min-width: 0;
      flex: 0 0 auto;
    `,
    contextRingButton: css`
      width: 32px;
      height: 32px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 0;
      border: 0;
      border-radius: 9px;
      background: transparent;
      color: rgba(255, 255, 255, 0.72);
      cursor: pointer;
      transition: background 160ms ease, color 160ms ease;
      &:hover,
      &:focus-visible {
        background: rgba(255, 255, 255, 0.08);
        color: rgba(255, 255, 255, 0.92);
        outline: none;
      }
      svg { width: 24px; height: 24px; transform: rotate(-90deg); }
      circle { fill: none; stroke-width: 3.5; }
      .track { stroke: rgba(255, 255, 255, 0.14); }
      .value { stroke: currentColor; stroke-linecap: round; transition: stroke-dasharray 220ms ease; }
    `,
    contextRingEmpty: css`color: rgba(255, 255, 255, 0.38);`,
    contextRingNormal: css`color: rgba(255, 255, 255, 0.82);`,
    contextRingWarning: css`color: #f0b55a;`,
    contextRingCritical: css`color: #ff7373;`,
    contextPopover: css`
      width: min(310px, calc(100vw - 40px));
      display: inline-flex;
      flex-direction: column;
      gap: 12px;
      padding: 4px;
      color: rgba(255, 255, 255, 0.9);
      font-size: 12px;
      line-height: 18px;
      small { color: rgba(255, 255, 255, 0.42); }
    `,
    contextPopoverHeader: css`
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 20px;
      strong { font-size: 15px; }
      span { color: rgba(255, 255, 255, 0.58); font-variant-numeric: tabular-nums; white-space: nowrap; }
    `,
    contextPopoverMetric: css`
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
      color: rgba(255, 255, 255, 0.55);
      strong { color: rgba(255, 255, 255, 0.9); font-size: 14px; font-variant-numeric: tabular-nums; }
    `,
    runtimeBadge: css`
      height: 32px;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      max-width: min(250px, 24vw);
      padding: 0 8px;
      border: 0;
      border-radius: 9px;
      background: transparent;
      color: rgba(255, 255, 255, 0.78);
      font: inherit;
      font-size: 13px;
      line-height: 20px;
      white-space: nowrap;
      cursor: pointer;
      transition: background 160ms ease, color 160ms ease;
      span { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
      .anticon:last-child { color: rgba(255, 255, 255, 0.34); font-size: 9px; }
      &:hover,
      &:focus-visible {
        background: rgba(255, 255, 255, 0.08);
        color: rgba(255, 255, 255, 0.95);
        outline: none;
      }
      @media (max-width: 900px) {
        max-width: 150px;
      }
      @media (max-width: 680px) {
        width: 32px;
        justify-content: center;
        padding: 0;
        span, .anticon:last-child { display: none; }
      }
    `,
    permissionButton: css`
      height: 32px;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 0 9px;
      border: 0;
      border-radius: 9px;
      background: transparent;
      color: rgba(255, 255, 255, 0.68);
      font: inherit;
      font-size: 13px;
      white-space: nowrap;
      cursor: pointer;
      transition: background 160ms ease, color 160ms ease;
      .anticon:last-child { color: currentColor; opacity: 0.5; font-size: 9px; }
      &:hover,
      &:focus-visible { background: rgba(255, 255, 255, 0.08); color: rgba(255, 255, 255, 0.92); outline: none; }
      &:disabled { cursor: default; opacity: 0.82; }
      &:disabled:hover { background: transparent; }
      @media (max-width: 680px) {
        span { display: none; }
      }
    `,
    permissionButtonFull: css`color: #ff8a24;`,
    launchConfigButton: css`
      height: 32px;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 0 9px;
      border: 0;
      border-radius: 9px;
      background: transparent;
      color: rgba(255, 255, 255, 0.48);
      font: inherit;
      font-size: 13px;
      cursor: pointer;
      &:hover,
      &:focus-visible { background: rgba(255, 255, 255, 0.08); color: rgba(255, 255, 255, 0.85); outline: none; }
      @media (max-width: 760px) { span { display: none; } }
    `,
    launchEditorHeading: css`
      display: flex;
      flex-direction: column;
      gap: 2px;
      strong { color: rgba(255, 255, 255, 0.92); font-size: 15px; }
      span { color: rgba(255, 255, 255, 0.45); font-size: 12px; }
    `,
    launchEditorField: css`
      display: flex;
      flex-direction: column;
      gap: 6px;
      > span { color: rgba(255, 255, 255, 0.64); font-size: 12px; }
      .ant-select { width: 100%; }
    `,
    launchEditorGrid: css`
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      @media (max-width: 480px) { grid-template-columns: 1fr; }
    `,
    sendSlot: css`
      flex: 0 0 auto;
      .ant-btn {
        width: 38px;
        height: 38px;
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
      .ant-sender-content {
        padding: 4px 8px 2px;
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
