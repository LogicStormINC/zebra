import { Actions } from "@ant-design/x";
import XMarkdown from "@ant-design/x-markdown";
import { createStyles } from "antd-style";
import { clsx } from "clsx";
import type { ReactNode } from "react";
import type { ChatMessage } from "../core/public-types.ts";

const useStyle = createStyles(({ css }) => {
  return {
    assistantBlock: css`
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-sm);
      color: rgba(255, 255, 255, 0.92);
    `,
    assistantMeta: css`
      display: flex;
      align-items: center;
      gap: var(--zebra-space-xs);
      color: rgba(255, 255, 255, 0.45);
      font-size: var(--zebra-font-size-sm);
      font-weight: var(--zebra-font-weight-medium);
      letter-spacing: 0.02em;
    `,
    statusDot: css`
      width: var(--zebra-icon-dot);
      height: var(--zebra-icon-dot);
      border-radius: 50%;
      background: #8f8f8f;
    `,
    assistantBody: css`
      display: flex;
      flex-direction: column;
      gap: var(--zebra-space-md);
    `,
    markdown: css`
      color: rgba(255, 255, 255, 0.92);
      font-size: var(--zebra-font-size-md);
      line-height: var(--zebra-line-height-relaxed);
      p {
        margin: 0 0 var(--zebra-space-sm);
      }
      p:last-child {
        margin-bottom: 0;
      }
      ol,
      ul {
        margin: 0 0 var(--zebra-space-lg) var(--zebra-space-xl);
      }
      li + li {
        margin-top: var(--zebra-space-xs);
      }
      code {
        background: rgba(255, 255, 255, 0.1);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: var(--zebra-radius-pill);
        padding: var(--zebra-space-3xs) var(--zebra-space-sm);
        font-size: var(--zebra-font-size-code);
      }
      pre {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: var(--zebra-radius-card);
        padding: var(--zebra-space-sm) var(--zebra-space-md);
        overflow: auto;
      }
      blockquote {
        margin: 0;
        padding-left: var(--zebra-space-md);
        border-left: var(--zebra-line-indent-step) solid rgba(255, 255, 255, 0.12);
        color: rgba(255, 255, 255, 0.66);
      }
    `,
    assistantActions: css`
      display: flex;
      align-items: center;
      gap: var(--zebra-space-sm);
      color: rgba(255, 255, 255, 0.45);
    `,
  };
});

interface AssistantMessageProps {
  message: ChatMessage;
  agentLabel?: string;
  /** Consumer-specific content rendered above the markdown body. */
  renderBefore?: ReactNode;
  /**
   * Exact-final-bound sources (e.g. artifact/review references). Rendered
   * inside the assistant block, after the markdown body and before the
   * message tail actions, so sources are always bound to this exact message.
   */
  renderSources?: (message: ChatMessage) => ReactNode;
  /** Extra message actions rendered after the built-in copy action. */
  renderMessageActions?: (message: ChatMessage) => ReactNode;
}

export function AssistantMessage({
  message,
  agentLabel = "Zebra Agent",
  renderBefore,
  renderSources,
  renderMessageActions,
}: AssistantMessageProps) {
  const { styles } = useStyle();

  return (
    <section className={styles.assistantBlock}>
      <div className={styles.assistantMeta}>
        <span className={styles.statusDot} />
        <span>{agentLabel}</span>
      </div>
      <div className={styles.assistantBody}>
        {renderBefore}
        <XMarkdown className={clsx("x-markdown", styles.markdown)} paragraphTag="div">
          {message.content}
        </XMarkdown>
        {renderSources?.(message)}
      </div>
      <div className={styles.assistantActions}>
        <Actions
          items={[
            {
              key: "copy",
              actionRender: <Actions.Copy text={message.content} />,
            },
          ]}
        />
        {renderMessageActions?.(message)}
      </div>
    </section>
  );
}
