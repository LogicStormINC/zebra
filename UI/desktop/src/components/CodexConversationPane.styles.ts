import { createStyles } from "antd-style";

export const useConversationPaneStyle = createStyles(({ css }) => {
  return {
    main: css`
      min-width: 0;
      display: flex;
      flex-direction: column;
      min-height: 100vh;
    `,
    topbar: css`
      min-height: var(--zebra-topbar-height);
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--zebra-space-sm) var(--zebra-space-md);
      background: rgba(22, 22, 22, 0.82);
      backdrop-filter: blur(20px);
      position: sticky;
      top: 0;
      z-index: 5;
      @media (max-width: 768px) {
        flex-direction: column;
        align-items: stretch;
        gap: var(--zebra-space-xs);
        padding: var(--zebra-space-sm);
        min-height: auto;
      }
      @media (min-width: 1280px) {
        padding: var(--zebra-space-sm) var(--zebra-space-lg);
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
      border-radius: var(--zebra-radius-soft);
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.05);
      color: rgba(255, 255, 255, 0.86);
    `,
    titleBlock: css`
      min-width: 0;
      display: flex;
      align-items: center;
      gap: var(--zebra-space-xs);
      h1 {
        margin: 0;
        font-size: clamp(18px, 2vw, var(--zebra-font-size-2xl));
        font-weight: var(--zebra-font-weight-semibold);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
    `,
    titleMeta: css`
      color: rgba(255, 255, 255, 0.45);
      font-size: var(--zebra-font-size-2xs);
      white-space: nowrap;
    `,
    headerActions: css`
      display: flex;
      align-items: center;
      gap: var(--zebra-space-xs);
    `,
    workspaceBadge: css`
      display: inline-flex;
      align-items: center;
      gap: var(--zebra-space-xs);
      padding: var(--zebra-space-xs) var(--zebra-space-sm);
      border-radius: var(--zebra-radius-soft);
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.08);
      color: rgba(255, 255, 255, 0.88);
    `,
    actionButton: css`
      background: transparent;
      border-color: rgba(255, 255, 255, 0.08);
      color: rgba(255, 255, 255, 0.7);
      &:hover {
        color: white !important;
        border-color: rgba(255, 255, 255, 0.16) !important;
        background: rgba(255, 255, 255, 0.04) !important;
      }
    `,
    center: css`
      flex: 1;
      min-height: 0;
      display: flex;
      flex-direction: column;
      padding: 0 var(--zebra-space-md) var(--zebra-space-lg);
      @media (max-width: 768px) {
        padding: 0 var(--zebra-space-sm) var(--zebra-space-md);
      }
      @media (min-width: 1280px) {
        padding: 0 var(--zebra-space-lg) var(--zebra-space-xl);
      }
    `,
    stream: css`
      flex: 1;
      overflow-y: auto;
      padding: var(--zebra-space-md) 0 var(--zebra-space-md);
    `,
    streamInner: css`
      width: var(--zebra-pane-max);
      margin: 0 auto;
      position: relative;
      padding-left: var(--zebra-space-lg);
      &::before {
        content: "";
        position: absolute;
        left: calc(var(--zebra-space-lg) * 0.5);
        top: var(--zebra-space-sm);
        bottom: var(--zebra-space-sm);
        width: var(--zebra-timeline-width);
        border-radius: var(--zebra-radius-pill);
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.11), rgba(255, 255, 255, 0.02));
      }
      @media (max-width: 767px) {
        padding-left: 0;
        &::before {
          display: none;
        }
      }
    `,
    emptyState: css`
      min-height: var(--zebra-empty-min);
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: var(--zebra-space-lg);
    `,
    eyebrow: css`
      color: #ffb067;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: var(--zebra-font-size-2xs);
      font-weight: var(--zebra-font-weight-bold);
    `,
    emptyTitle: css`
      margin: 0;
      max-width: var(--zebra-empty-title-max);
      font-size: var(--zebra-font-size-2xl);
      line-height: 1.08;
      letter-spacing: -0.03em;
      font-weight: var(--zebra-font-weight-semibold);
    `,
    emptyCopy: css`
      max-width: var(--zebra-empty-copy-max);
      color: rgba(255, 255, 255, 0.58);
      font-size: var(--zebra-font-size-md);
      line-height: var(--zebra-line-height-relaxed);
    `,
    hintRow: css`
      display: flex;
      flex-wrap: wrap;
      gap: var(--zebra-space-sm);
    `,
    hintChip: css`
      padding: var(--zebra-space-xs) var(--zebra-space-md);
      border-radius: var(--zebra-radius-pill);
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.05);
      color: rgba(255, 255, 255, 0.72);
      font-size: var(--zebra-font-size-xs);
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
      background: linear-gradient(180deg, #2b2b2b 0%, #252525 100%);
      border: 1px solid rgba(255, 255, 255, 0.08);
      color: rgba(255, 255, 255, 0.9);
      font-size: var(--zebra-font-size-sm);
      line-height: var(--zebra-line-height-relaxed);
      box-shadow: var(--zebra-shadow-sm);
    `,
    composerDock: css`
      width: var(--zebra-content-max);
      margin: 0 auto;
      padding-top: var(--zebra-space-md);
    `,
    composerCard: css`
      background: linear-gradient(180deg, #2a2a2a 0%, #232323 100%);
      border: 1px solid rgba(255, 255, 255, 0.09);
      border-radius: var(--zebra-radius-composer);
      box-shadow: var(--zebra-shadow-lg);
      padding: var(--zebra-space-sm);
    `,
    composerFooter: css`
      padding: 0 var(--zebra-space-xs) var(--zebra-space-xs);
    `,
    permissionTag: css`
      display: inline-flex;
      align-items: center;
      gap: var(--zebra-space-xs);
      color: #f6a256;
      font-size: var(--zebra-font-size-2xs);
      font-weight: var(--zebra-font-weight-medium);
      span:first-child {
        width: calc(var(--zebra-icon-dot) + 1px);
        height: calc(var(--zebra-icon-dot) + 1px);
        border-radius: 50%;
        background: currentColor;
        box-shadow: var(--zebra-shadow-ambient);
      }
    `,
    footerMeta: css`
      color: rgba(255, 255, 255, 0.54);
      font-size: var(--zebra-font-size-2xs);
      white-space: nowrap;
    `,
    sender: css`
      .ant-sender {
        background: transparent;
      }
      .ant-sender-textarea {
        color: white;
        font-size: var(--zebra-font-size-sm);
      }
      .ant-sender-textarea::placeholder {
        color: rgba(255, 255, 255, 0.34);
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
