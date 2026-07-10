import { Actions } from "@ant-design/x";
import XMarkdown from "@ant-design/x-markdown";
import { Tag } from "antd";
import { createStyles } from "antd-style";
import { clsx } from "clsx";
import "@ant-design/x-markdown/themes/dark.css";
import locale from "../_utils/local";
import type { ChatMessage } from "../lib/chat-surface";
import { useMarkdownTheme } from "../x-markdown/demo/_utils";
import { AssistantInsightCards } from "./AssistantInsightCards";

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
    statusDotLoading: css`
      background: #f28c38;
      box-shadow: var(--zebra-shadow-chip);
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

export function AssistantMessageBlock({ message }: { message: ChatMessage }) {
  const [className] = useMarkdownTheme();
  const { styles } = useStyle();

  return (
    <section className={styles.assistantBlock}>
      <div className={styles.assistantMeta}>
        <span className={clsx(styles.statusDot, message.status === "loading" && styles.statusDotLoading)} />
        <span>Zebra Agent</span>
        {message.status === "loading" ? <Tag color="orange">{locale.generating}</Tag> : null}
      </div>
      <div className={styles.assistantBody}>
        <AssistantInsightCards content={message.content} />
        <XMarkdown className={clsx(className, styles.markdown)} paragraphTag="div">
          {message.content}
        </XMarkdown>
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
      </div>
    </section>
  );
}
